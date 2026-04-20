"""Pydantic models for scenario YAML files."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ApprovalAction(BaseModel):
    decision: str = Field(..., pattern=r"^(approve|reject|edit)$")
    edits: dict | None = None


class UserTurn(BaseModel):
    message: str
    approvals: list[ApprovalAction] = Field(default_factory=list)


class ExpectedOutcome(BaseModel):
    final_event: str = "final"
    artifacts_of_type: list[str] = Field(default_factory=list)
    min_agent_invocations: int = 1
    max_wall_time_ms: int = 30000


class Scenario(BaseModel):
    id: int
    name: str
    persona: str
    course_id: str
    user_turns: list[UserTurn]
    expected: ExpectedOutcome
