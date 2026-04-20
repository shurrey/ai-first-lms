from __future__ import annotations

from fastapi import FastAPI

from engine.api.approval import router as approval_router
from engine.api.converse import router as converse_router
from engine.api.session import router as session_router
from engine.api.stream import router as stream_router
from engine.db import SessionStore, TurnStore
from engine.guardrails.approval import ApprovalGate


def create_app() -> FastAPI:
    """Application factory for the AI-First LMS orchestrator."""
    app = FastAPI(
        title="AI-First LMS Orchestrator",
        version="0.1.0",
    )

    app.state.session_store = SessionStore()
    app.state.turn_store = TurnStore()
    app.state.approval_gate = ApprovalGate()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(session_router)
    app.include_router(converse_router)
    app.include_router(stream_router)
    app.include_router(approval_router)

    return app
