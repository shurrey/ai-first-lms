"""Pydantic models for every SSE event type per contracts/events.md."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Payload types ---

class ReasoningPayload(BaseModel):
    step: Literal["interpret", "clarify", "plan", "dispatch", "synthesize"]
    text: str


class PlanStepPayload(BaseModel):
    step_id: str
    agent: str
    input_summary: str
    depends_on: list[str] = Field(default_factory=list)


class PlanPayload(BaseModel):
    strategy: Literal["react", "plan_then_execute"]
    steps: list[PlanStepPayload]
    estimated_cost_usd: float
    estimated_tokens: int


class AgentStartPayload(BaseModel):
    step_id: str
    agent: str
    inputs: dict[str, Any]


class AgentTokenPayload(BaseModel):
    step_id: str
    agent: str
    delta: str
    channel: Literal["thought", "response"]


class AgentToolCallPayload(BaseModel):
    step_id: str
    agent: str
    tool: str
    arguments: dict[str, Any]
    result_summary: str
    latency_ms: float
    success: bool


class AgentResultPayload(BaseModel):
    step_id: str
    agent: str
    output: dict[str, Any]
    cost_usd: float
    tokens: int
    success: bool


class ClarifyPayload(BaseModel):
    question: str
    reason: str
    options: list[str] | None = None


class ApprovalRequestPayload(BaseModel):
    approval_id: str
    step_id: str
    agent: str
    action: str
    preview: dict[str, Any]
    artifact_type: Literal[
        "rubric_grades", "message", "quiz", "content_draft", "other"
    ]


class ArtifactPayload(BaseModel):
    artifact_id: str
    type: Literal[
        "rubric_grades", "message", "quiz", "chart", "degree_audit",
        "content_draft", "wcag_report", "risk_list", "learning_path"
    ]
    data: dict[str, Any]


class FinalPayload(BaseModel):
    answer_markdown: str
    artifacts: list[ArtifactPayload] = Field(default_factory=list)
    cost_usd: float
    tokens: int
    wall_time_ms: float


class ErrorPayload(BaseModel):
    code: Literal[
        "budget_exceeded", "permission_denied", "agent_failure",
        "mcp_failure", "llm_failure", "timeout", "internal"
    ]
    message: str
    retriable: bool
    step_id: str | None = None


# --- Union of all event types ---

EventType = Literal[
    "reasoning", "plan", "agent_start", "agent_token", "agent_tool_call",
    "agent_result", "clarify", "approval_request", "final", "error",
]

Payload = (
    ReasoningPayload
    | PlanPayload
    | AgentStartPayload
    | AgentTokenPayload
    | AgentToolCallPayload
    | AgentResultPayload
    | ClarifyPayload
    | ApprovalRequestPayload
    | FinalPayload
    | ErrorPayload
)


class EventEnvelope(BaseModel):
    """SSE event envelope — contracts/events.md."""

    event: EventType
    session_id: str
    turn_id: str
    sequence: int
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    payload: Payload
