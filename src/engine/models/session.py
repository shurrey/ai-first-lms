from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona: str  # student | faculty | advisor | admin
    person_id: str | None = None
    course_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict | None = None


class CreateSessionRequest(BaseModel):
    persona: str
    person_id: str | None = None
    course_id: str


class CreateSessionResponse(BaseModel):
    session_id: str
