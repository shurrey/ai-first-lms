"""FastAPI dependencies: session resolution, current_user() and the CSRF check.

Session and AuthContext are resolved at most once per request and cached on
request.state, so the global CSRF dependency and current_user() share one lookup.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from engine.auth.config import CSRF_HEADER, SESSION_COOKIE
from engine.auth.models import AuthContext, SessionRecord
from engine.auth.service import AuthService

COOKIE_REFRESH_STATE = "auth_cookie_refresh"
"""request.state key holding (token, csrf) when sliding expiry wants the cookies re-sent."""

_SESSION_STATE = "auth_session"
_CONTEXT_STATE = "auth_context"
_UNRESOLVED = object()
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})


def optional_auth_service(request: Request) -> AuthService | None:
    return getattr(request.app.state, "auth_service", None)


def get_auth_service(request: Request) -> AuthService:
    """503 when the engine was started without an auth database."""
    service = optional_auth_service(request)
    if service is None:
        raise HTTPException(status_code=503, detail="Sign-in is unavailable.")
    return service


async def resolve_session(request: Request) -> SessionRecord | None:
    """The live session named by the cookie, or None. Slides expiry as a side effect."""
    cached = getattr(request.state, _SESSION_STATE, _UNRESOLVED)
    if cached is not _UNRESOLVED:
        return cached  # type: ignore[return-value]
    session: SessionRecord | None = None
    token = request.cookies.get(SESSION_COOKIE)
    service = optional_auth_service(request)
    if token and service is not None:
        found = await service.sessions.lookup(token)
        if found is not None:
            session = found.session
            if found.slid:
                setattr(request.state, COOKIE_REFRESH_STATE, (token, session.csrf_token))
    setattr(request.state, _SESSION_STATE, session)
    return session


async def current_user(request: Request) -> AuthContext:
    """401 when there is no valid session; 503 when auth storage is not configured."""
    cached = getattr(request.state, _CONTEXT_STATE, None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    service = get_auth_service(request)
    session = await resolve_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    ctx = await service.load_context(session)
    if ctx is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    setattr(request.state, _CONTEXT_STATE, ctx)
    return ctx


async def csrf_protect(request: Request) -> None:
    """Double-submit check for non-GET /api/* requests that carry a live session.

    A request without a live session has no ambient credential to abuse, so it
    passes here and is left to the endpoint's own authentication.
    """
    if request.method in _SAFE_METHODS:
        return
    path = request.url.path
    if not path.startswith("/api/") or path in _CSRF_EXEMPT_PATHS:
        return
    session = await resolve_session(request)
    if session is None:
        return
    sent = request.headers.get(CSRF_HEADER, "")
    # compare_digest raises TypeError on non-ASCII str, so compare bytes.
    if not sent or not hmac.compare_digest(
        sent.encode("utf-8", "surrogateescape"), session.csrf_token.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")


def forget_session(request: Request) -> None:
    """Drops the per-request cache, e.g. after the session's role or validity changed."""
    for key in (_SESSION_STATE, _CONTEXT_STATE, COOKIE_REFRESH_STATE):
        if hasattr(request.state, key):
            delattr(request.state, key)


CurrentUser = Annotated[AuthContext, Depends(current_user)]
