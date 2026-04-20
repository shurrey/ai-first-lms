from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from engine.models.session import CreateSessionRequest, CreateSessionResponse, Session

router = APIRouter()

VALID_PERSONAS = {"student", "faculty", "advisor", "admin"}


@router.post("/api/session", status_code=201, response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    if body.persona not in VALID_PERSONAS:
        raise HTTPException(status_code=422, detail=f"Invalid persona: {body.persona}")

    session = Session(
        persona=body.persona,
        person_id=body.person_id,
        course_id=body.course_id,
    )
    store = request.app.state.session_store
    await store.create(session)
    return CreateSessionResponse(session_id=session.id)
