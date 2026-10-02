"""/api/auth/* — sign-in, sign-out, /me, role switch and password change."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from engine.auth.config import SESSION_COOKIE
from engine.auth.cookies import clear_auth_cookies, set_auth_cookies
from engine.auth.deps import current_user, forget_session, get_auth_service, resolve_session
from engine.auth.me import build_me
from engine.auth.models import AuthContext
from engine.auth.service import AuthService, PasswordChange, known_roles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_FAILED = "Invalid username or password."

Service = Annotated[AuthService, Depends(get_auth_service)]
CurrentUser = Annotated[AuthContext, Depends(current_user)]

PersonRole = Literal["student", "faculty", "program_lead", "advisor", "admin"]


class LoginRequest(BaseModel):
    username: str
    password: str


class RoleRequest(BaseModel):
    role: PersonRole


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


async def _me(service: AuthService, ctx: AuthContext) -> dict[str, Any]:
    return build_me(ctx, await service.must_change_password(ctx.person_id))


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: Service,
) -> dict[str, Any]:
    person = await service.authenticate(body.username, body.password)
    if person is None:
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    previous = request.cookies.get(SESSION_COOKIE)
    if previous:
        old = await service.sessions.peek(previous)
        if old is not None:
            await service.sessions.revoke(old.id)

    active_role = known_roles(person.roles)[0]
    token, session = await service.sessions.create(
        person.id, active_role, request.headers.get("user-agent")
    )
    ctx = await service.load_context(session)
    if ctx is None:
        await service.sessions.revoke(session.id)
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    set_auth_cookies(response, token, session.csrf_token, service.settings)
    logger.info("login succeeded", extra={"person_id": person.id, "active_role": active_role})
    return await _me(service, ctx)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    service: Service,
) -> Response:
    """Clears both cookies even when the session is already expired, revoked or absent."""
    session = await resolve_session(request)
    if session is not None:
        await service.sessions.revoke(session.id)
    forget_session(request)
    response = Response(status_code=204)
    clear_auth_cookies(response, service.settings)
    return response


@router.get("/me")
async def me(
    ctx: CurrentUser,
    service: Service,
) -> dict[str, Any]:
    return await _me(service, ctx)


@router.post("/role")
async def switch_role(
    body: RoleRequest,
    ctx: CurrentUser,
    service: Service,
) -> dict[str, Any]:
    if body.role not in ctx.roles:
        raise HTTPException(status_code=403, detail="You do not hold that role.")
    if body.role != ctx.active_role:
        await service.sessions.set_role(ctx.session_id, body.role)
        logger.info(
            "active role switched",
            extra={"person_id": ctx.person_id, "from_role": ctx.active_role, "to_role": body.role},
        )
    return await _me(service, replace(ctx, active_role=body.role))


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    ctx: CurrentUser,
    service: Service,
) -> Response:
    result = await service.change_password(ctx, body.current_password, body.new_password)
    if result is PasswordChange.LOCKED:
        forget_session(request)
        response = JSONResponse(status_code=401, content={"detail": "Not authenticated."})
        clear_auth_cookies(response, service.settings)
        return response
    if result is PasswordChange.WRONG:
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    logger.info("password changed", extra={"person_id": ctx.person_id})
    return Response(status_code=204)
