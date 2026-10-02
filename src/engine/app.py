from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engine.agents.runner import _execute_mcp
from engine.api.approval import router as approval_router
from engine.api.auth import router as auth_router
from engine.api.converse import router as converse_router
from engine.api.credentials import router as credentials_router
from engine.api.podcast import router as podcast_router
from engine.api.roster import router as roster_router
from engine.api.session import router as session_router
from engine.api.stream import router as stream_router
from engine.auth.config import CSRF_HEADER, AuthSettings
from engine.auth.deps import csrf_protect
from engine.auth.directory import PgScopeDirectory, ScopeDirectory
from engine.auth.middleware import SessionCookieRefreshMiddleware
from engine.auth.passwords import PasswordService
from engine.auth.repository import PgAuthRepository, create_pool
from engine.auth.service import AuthService
from engine.db import SessionStore, TurnStore
from engine.guardrails.approval import ApprovalGate
from engine.guardrails.gateway import ToolGateway
from engine.guardrails.object_directory import ObjectDirectory, PgObjectDirectory
from engine.http import log_tls_mode
from engine.logging_config import setup_logging
from engine.telemetry import setup_telemetry
from engine.turn_repository import Persistence, PgTurnRepository

logger = logging.getLogger(__name__)

ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:3100"]

_TRUTHY = {"1", "true", "yes", "on"}


def _api_docs_enabled() -> bool:
    """/docs, /redoc and /openapi.json are served only when ENGINE_API_DOCS is truthy."""
    return os.environ.get("ENGINE_API_DOCS", "false").strip().lower() in _TRUTHY


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422 body, minus the submitted values on /api/auth/*.

    The default echoes each invalid field's `input`, which there would be a password.
    """
    errors = exc.errors()
    if request.url.path.startswith("/api/auth/"):
        errors = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in errors]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


def _tool_gateway(app: FastAPI, turns: Persistence | None) -> ToolGateway:
    return ToolGateway(
        _execute_mcp,
        directory=app.state.scope_directory,
        objects=app.state.object_directory,
        turns=turns,
        approvals=app.state.approval_gate,
        turn_status=app.state.turn_store,
    )


def _use_persistence(app: FastAPI, repository: Persistence | None) -> None:
    app.state.persistence = repository
    app.state.session_store.use_repository(repository)
    app.state.turn_store.use_repository(repository)
    app.state.tool_gateway = _tool_gateway(app, repository)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Opens the DATABASE_URL pool for auth and scope checks unless both were injected.

    That pool also backs the gateway's object lookups and session/turn persistence unless
    those were injected.
    """
    pool = None
    needs_auth = app.state.auth_service is None
    needs_directory = app.state.scope_directory is None
    needs_objects = app.state.object_directory is None
    if needs_auth or needs_directory:
        dsn = os.environ.get("DATABASE_URL")
        if dsn:
            pool = await create_pool(dsn)
            app.state.db_pool = pool
            if needs_auth:
                app.state.auth_service = AuthService(
                    PgAuthRepository(pool), app.state.auth_settings, PasswordService()
                )
            if needs_directory:
                app.state.scope_directory = PgScopeDirectory(pool)
            if needs_objects:
                app.state.object_directory = PgObjectDirectory(pool)
            if not app.state.persistence_injected:
                _use_persistence(app, PgTurnRepository(pool))
            else:
                app.state.tool_gateway = _tool_gateway(app, app.state.persistence)
        else:
            logger.warning("DATABASE_URL is not set; authenticated endpoints will return 503")
    try:
        yield
    finally:
        if pool is not None:
            if needs_auth:
                app.state.auth_service = None
            if needs_directory:
                app.state.scope_directory = None
            if needs_objects:
                app.state.object_directory = None
            app.state.db_pool = None
            if not app.state.persistence_injected:
                _use_persistence(app, None)
            else:
                app.state.tool_gateway = _tool_gateway(app, app.state.persistence)
            await pool.close()


def create_app(
    auth_service: AuthService | None = None,
    scope_directory: ScopeDirectory | None = None,
    persistence: Persistence | None = None,
    object_directory: ObjectDirectory | None = None,
) -> FastAPI:
    """Application factory for the AI-First LMS orchestrator.

    Pass `auth_service` / `scope_directory` / `persistence` / `object_directory` to use
    specific stores (tests); otherwise the lifespan builds them from DATABASE_URL.
    """
    setup_logging()
    log_tls_mode()

    settings = auth_service.settings if auth_service is not None else AuthSettings.from_env()

    docs = _api_docs_enabled()
    app = FastAPI(
        title="AI-First LMS Orchestrator",
        version="0.1.0",
        lifespan=_lifespan,
        dependencies=[Depends(csrf_protect)],
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_exception_handler(RequestValidationError, _validation_error)

    app.add_middleware(SessionCookieRefreshMiddleware, settings=settings)
    # Added last so it is outermost and decorates every response, including errors.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Last-Event-ID", CSRF_HEADER],
    )

    app.state.auth_settings = settings
    app.state.auth_service = auth_service
    app.state.scope_directory = scope_directory
    app.state.object_directory = object_directory
    app.state.db_pool = None
    app.state.background_tasks = set()

    app.state.session_store = SessionStore()
    app.state.turn_store = TurnStore()
    app.state.approval_gate = ApprovalGate()
    app.state.persistence_injected = persistence is not None
    _use_persistence(app, persistence)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(session_router)
    app.include_router(converse_router)
    app.include_router(stream_router)
    app.include_router(approval_router)
    app.include_router(podcast_router)
    app.include_router(roster_router)
    app.include_router(credentials_router)

    setup_telemetry(app)
    return app
