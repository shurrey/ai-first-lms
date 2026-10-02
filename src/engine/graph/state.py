"""Orchestrator state schema for the LangGraph state machine (SPEC §4.2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from engine.auth.models import AuthContext
from engine.guardrails.budget import BudgetTracker
from engine.guardrails.gateway import ToolGateway


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
    # {display_name, active_role} of the signed-in person (spec.md §4.5).
    requester: dict[str, str]
    # The signed-in caller; tool calls are denied when absent.
    auth: AuthContext
    tool_gateway: ToolGateway
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
    # Per-turn caps; shared by reference across nodes and the agent runner.
    budget: BudgetTracker
    # ErrorPayload (contracts/events.md) that halted the turn; None while the turn is healthy.
    turn_error: dict[str, Any] | None
    events_emitted: list[dict[str, Any]]
    # Pushes an event to this turn's stream immediately; absent outside /api/converse.
    event_sink: Callable[[dict[str, Any]], Awaitable[None]]
    needs_clarification: bool
