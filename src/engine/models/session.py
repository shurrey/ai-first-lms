from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona: str  # the creator's active_role: student | faculty | program_lead | advisor | admin
    person_id: str | None = None
    course_id: str
    requester_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict | None = None


class CreateSessionRequest(BaseModel):
    """Unknown fields (the removed `persona`, `person_id`) are ignored."""

    course_id: str
    page: str | None = None  # Optional page brief: "content", "gradebook", "roster", "calendar", "analytics"


class CreateSessionResponse(BaseModel):
    session_id: str
    person_id: str | None = None
    course_uuid: str | None = None
    brief_turn_id: str | None = None
    stream_url: str | None = None
