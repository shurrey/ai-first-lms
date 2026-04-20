from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Application factory for the AI-First LMS orchestrator."""
    app = FastAPI(
        title="AI-First LMS Orchestrator",
        version="0.1.0",
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
