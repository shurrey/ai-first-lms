"""Set-Cookie handling for `lms_session` and `lms_csrf`."""

from __future__ import annotations

from starlette.responses import Response

from engine.auth.config import CSRF_COOKIE, SESSION_COOKIE, AuthSettings


def set_auth_cookies(response: Response, token: str, csrf: str, settings: AuthSettings) -> None:
    common = {
        "max_age": settings.cookie_max_age,
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": "lax",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)  # type: ignore[arg-type]


def clear_auth_cookies(response: Response, settings: AuthSettings) -> None:
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(
            name, path="/", secure=settings.cookie_secure, httponly=httponly, samesite="lax"
        )


def auth_cookie_headers(token: str, csrf: str, settings: AuthSettings) -> list[bytes]:
    """The two Set-Cookie header values, for code that writes raw ASGI headers."""
    scratch = Response()
    set_auth_cookies(scratch, token, csrf, settings)
    return [value for key, value in scratch.raw_headers if key == b"set-cookie"]
