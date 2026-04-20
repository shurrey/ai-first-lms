from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from engine.models.session import CreateSessionRequest, CreateSessionResponse, Session
from engine.models.turn import Turn

router = APIRouter()

VALID_PERSONAS = {"student", "faculty", "advisor", "admin"}

_COURSE_SLUG_TO_UUID: dict[str, str] = {
    "cs101": "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
}

_DEMO_STUDENTS: dict[str, tuple[str, str]] = {
    "bdd640fb-0667-4ad1-9c80-317fa3b1799d": (
        "17fc695a-07a0-4a6e-8822-e8f36c031199", "Emma Smith"
    ),
}


@router.post("/api/session", status_code=201, response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    if body.persona not in VALID_PERSONAS:
        raise HTTPException(status_code=422, detail=f"Invalid persona: {body.persona}")

    course_id = _COURSE_SLUG_TO_UUID.get(body.course_id, body.course_id)

    person_id = body.person_id
    if not person_id and body.persona == "student" and course_id in _DEMO_STUDENTS:
        person_id = _DEMO_STUDENTS[course_id][0]

    session = Session(
        persona=body.persona,
        person_id=person_id,
        course_id=course_id,
    )
    store = request.app.state.session_store
    await store.create(session)

    # Create a brief turn and fire generation in background
    brief_turn_id = f"brief-{session.id}"
    brief_turn = Turn(session_id=session.id, message="__brief__")
    brief_turn.id = brief_turn_id
    turn_store = request.app.state.turn_store
    await turn_store.create(brief_turn)

    if person_id:
        from engine.brief import BriefGenerator
        generator = BriefGenerator()
        asyncio.create_task(
            generator.generate(
                persona=body.persona,
                person_id=person_id,
                course_id=course_id,
                turn_id=brief_turn_id,
                turn_store=turn_store,
            )
        )

    stream_url = f"/api/stream?session_id={session.id}&turn_id={brief_turn_id}"

    return CreateSessionResponse(
        session_id=session.id,
        brief_turn_id=brief_turn_id,
        stream_url=stream_url,
    )
