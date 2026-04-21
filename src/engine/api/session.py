from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from engine.models.session import CreateSessionRequest, CreateSessionResponse, Session
from engine.models.turn import Turn

router = APIRouter()

VALID_PERSONAS = {"student", "faculty", "advisor", "admin"}

_COURSE_SLUG_TO_UUID: dict[str, str] = {
    "all": "all",  # Cross-course view for advisor/admin
    "cs101": "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
    "math201": "23b8c1e9-3924-46de-beb1-3b9046685257",
    "eng102": "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9",
    "bio150": "972a8469-1641-4f82-8b9d-2434e465e150",
}

# All course UUIDs for cross-course queries
_ALL_COURSE_IDS = [
    "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
    "23b8c1e9-3924-46de-beb1-3b9046685257",
    "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9",
    "972a8469-1641-4f82-8b9d-2434e465e150",
]

# Demo person mappings per persona per course
_DEMO_PERSONS: dict[str, dict[str, tuple[str, str]]] = {
    "student": {
        "bdd640fb-0667-4ad1-9c80-317fa3b1799d": ("5be6128e-18c2-4797-a142-ea7d17be3111", "Emma Smith"),
        "23b8c1e9-3924-46de-beb1-3b9046685257": ("5be6128e-18c2-4797-a142-ea7d17be3111", "Emma Smith"),
        "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9": ("a2bc372f-7412-4293-8729-4739614ff3d7", "Noah Brown"),
        "972a8469-1641-4f82-8b9d-2434e465e150": ("5be6128e-18c2-4797-a142-ea7d17be3111", "Emma Smith"),
    },
    "faculty": {
        "bdd640fb-0667-4ad1-9c80-317fa3b1799d": ("17fc695a-07a0-4a6e-8822-e8f36c031199", "Dr. Maria Torres"),
        "23b8c1e9-3924-46de-beb1-3b9046685257": ("b74d0fb1-32e7-4629-8fad-c1a606cb0fb3", "Dr. Sarah Chen"),
        "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9": ("47378190-96da-4dac-b2ff-5d2a386ecbe0", "Dr. Emily Watson"),
        "972a8469-1641-4f82-8b9d-2434e465e150": ("c241330b-01a9-471f-9e8a-774bcf36d58b", "Dr. Michael Patel"),
    },
    "advisor": {
        "all": ("371ecd7b-27cd-4130-8722-9389571aa876", "Ms. Adaeze Okafor"),
        "bdd640fb-0667-4ad1-9c80-317fa3b1799d": ("371ecd7b-27cd-4130-8722-9389571aa876", "Ms. Adaeze Okafor"),
        "23b8c1e9-3924-46de-beb1-3b9046685257": ("371ecd7b-27cd-4130-8722-9389571aa876", "Ms. Adaeze Okafor"),
        "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9": ("371ecd7b-27cd-4130-8722-9389571aa876", "Ms. Adaeze Okafor"),
        "972a8469-1641-4f82-8b9d-2434e465e150": ("371ecd7b-27cd-4130-8722-9389571aa876", "Ms. Adaeze Okafor"),
    },
    "admin": {
        "all": ("1a2a73ed-562b-4f79-8374-59eef50bea63", "Dr. Richard Hayes"),
        "bdd640fb-0667-4ad1-9c80-317fa3b1799d": ("1a2a73ed-562b-4f79-8374-59eef50bea63", "Dr. Richard Hayes"),
        "23b8c1e9-3924-46de-beb1-3b9046685257": ("1a2a73ed-562b-4f79-8374-59eef50bea63", "Dr. Richard Hayes"),
        "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9": ("1a2a73ed-562b-4f79-8374-59eef50bea63", "Dr. Richard Hayes"),
        "972a8469-1641-4f82-8b9d-2434e465e150": ("1a2a73ed-562b-4f79-8374-59eef50bea63", "Dr. Richard Hayes"),
    },
}


@router.post("/api/session", status_code=201, response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    if body.persona not in VALID_PERSONAS:
        raise HTTPException(status_code=422, detail=f"Invalid persona: {body.persona}")

    course_id = _COURSE_SLUG_TO_UUID.get(body.course_id, body.course_id)

    # Auto-assign demo person based on persona + course
    person_id = body.person_id
    if not person_id:
        persona_map = _DEMO_PERSONS.get(body.persona, {})
        person_entry = persona_map.get(course_id)
        if person_entry:
            person_id = person_entry[0]

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
