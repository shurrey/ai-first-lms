"""Turn model — represents a single user↔assistant exchange."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Turn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "active"  # active | completed | error
    events: list[dict[str, Any]] = Field(default_factory=list)


class ConverseRequest(BaseModel):
    session_id: str
    message: str
    context_override: dict[str, Any] | None = None


class ConverseResponse(BaseModel):
    turn_id: str
    stream_url: str
