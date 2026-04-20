from __future__ import annotations

from fastapi import FastAPI

from engine.api.session import router as session_router
from engine.db import SessionStore


def create_app() -> FastAPI:
    """Application factory for the AI-First LMS orchestrator."""
    app = FastAPI(
        title="AI-First LMS Orchestrator",
        version="0.1.0",
    )

    app.state.session_store = SessionStore()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(session_router)

    return app
