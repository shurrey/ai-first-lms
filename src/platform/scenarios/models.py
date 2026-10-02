"""Pydantic models for scenario YAML files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PersonRole = Literal["student", "faculty", "program_lead", "advisor", "admin"]


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
    # Unknown keys are rejected so a stale `persona:` field fails loudly.
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    login_as: str = Field(..., min_length=1, description="Seeded username (the person's email).")
    active_role: PersonRole | None = Field(
        default=None,
        description="Role to switch to after login when it differs from the session's default.",
    )
    course_id: str
    user_turns: list[UserTurn]
    expected: ExpectedOutcome
