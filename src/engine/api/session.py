from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from engine.models.session import CreateSessionRequest, CreateSessionResponse, Session

router = APIRouter()

VALID_PERSONAS = {"student", "faculty", "advisor", "admin"}

# Demo mappings — in production these come from a real identity/enrollment service
_COURSE_SLUG_TO_UUID: dict[str, str] = {
    "cs101": "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
}

# Default demo student per course (first enrolled student)
_DEMO_STUDENTS: dict[str, tuple[str, str]] = {
    # course_uuid → (person_id, display_name)
    "bdd640fb-0667-4ad1-9c80-317fa3b1799d": (
        "17fc695a-07a0-4a6e-8822-e8f36c031199", "Emma Smith"
    ),
}


@router.post("/api/session", status_code=201, response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    if body.persona not in VALID_PERSONAS:
        raise HTTPException(status_code=422, detail=f"Invalid persona: {body.persona}")

    # Resolve course slug to UUID
    course_id = _COURSE_SLUG_TO_UUID.get(body.course_id, body.course_id)

    # Auto-assign demo student if none provided
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
    return CreateSessionResponse(session_id=session.id)
