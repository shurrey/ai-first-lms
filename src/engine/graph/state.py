"""Orchestrator state schema for the LangGraph state machine (SPEC §4.2)."""

from __future__ import annotations

from typing import Any, TypedDict


class Turn(TypedDict, total=False):
    role: str  # "user" | "assistant"
    content: str


class Intent(TypedDict, total=False):
    action: str
    agent: str
    parameters: dict[str, Any]
    confidence: float


class PlanStep(TypedDict, total=False):
    step_id: str
    agent: str
    input_summary: str
    depends_on: list[str]


class Plan(TypedDict, total=False):
    strategy: str  # "react" | "plan_then_execute"
    steps: list[PlanStep]


class AgentResult(TypedDict, total=False):
    step_id: str
    agent: str
    output: dict[str, Any]
    cost_usd: float
    tokens: int
    success: bool


class ApprovalRequest(TypedDict, total=False):
    approval_id: str
    step_id: str
    agent: str
    action: str
    preview: dict[str, Any]


class OrchestratorState(TypedDict, total=False):
    session_id: str
    turn_id: str
    persona: str
    person_id: str
    course_id: str
    conversation: list[Turn]
    current_message: str
    interpretation: Intent | None
    clarification: str | None
    plan: Plan | None
    plan_cursor: int
    agent_results: list[AgentResult]
    pending_approvals: list[ApprovalRequest]
    final_answer: str | None
    cost_usd: float
    tokens: int
    budget_exceeded: bool
    events_emitted: list[dict[str, Any]]
    needs_clarification: bool
