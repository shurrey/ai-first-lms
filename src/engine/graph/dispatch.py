"""Dispatch step — execute the plan by invoking sub-agents (SPEC §4.1 step 4)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

from opentelemetry import trace

from engine.agents.runner import AgentRunner, ClaudeAgentRunner
from engine.graph.state import AgentResult, OrchestratorState
from engine.guardrails.budget import BudgetTracker
from engine.guardrails.pii import scan_and_redact
from engine.guardrails.registry import get_manifest_registry, get_permission_matrix
from engine.logging_config import get_logger
from engine.telemetry import span_agent

logger = logging.getLogger(__name__)
log = get_logger(__name__)

BUDGET_EXCEEDED_MESSAGE = (
    "This request reached the usage limit for a single turn before it finished. "
    "Try a narrower question."
)

# Module-level agent runner, replaceable for testing
_agent_runner: AgentRunner | None = None

# Module-level event sink for real-time streaming
# Set by converse._run_graph before invoking the graph
_live_event_sink: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None


def set_live_event_sink(sink: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None) -> None:
    global _live_event_sink
    _live_event_sink = sink


def set_agent_runner(runner: AgentRunner | None) -> None:
    global _agent_runner  # noqa: PLW0603
    _agent_runner = runner


def get_agent_runner() -> AgentRunner:
    global _agent_runner  # noqa: PLW0603
    if _agent_runner is None:
        _agent_runner = ClaudeAgentRunner()
    return _agent_runner


async def dispatch(state: OrchestratorState) -> OrchestratorState:
    """Execute plan steps, invoking sub-agents and collecting results."""
    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        logger.warning("Dispatch called with no plan")
        return state

    steps = plan["steps"]
    runner = get_agent_runner()
    message = state.get("current_message", "")
    persona = state.get("persona", "student")
    person_id = state.get("person_id", "")
    course_id = state.get("course_id", "")
    session_id = state.get("session_id", "")
    conversation = state.get("conversation", [])
    budget = state.get("budget")
    events: list[dict[str, Any]] = list(state.get("events_emitted", []))
    results: list[AgentResult] = list(state.get("agent_results", []))
    completed_steps: dict[str, dict[str, Any]] = {}
    turn_error: dict[str, Any] | None = None

    # Group steps by dependency layer for execution
    remaining = list(steps)
    while remaining and turn_error is None:
        # Find steps whose dependencies are all satisfied
        ready = [
            s for s in remaining
            if all(dep in completed_steps for dep in s.get("depends_on", []))
        ]
        if not ready:
            logger.error("Deadlock: no steps ready but %d remaining", len(remaining))
            break

        # Execute ready steps (potentially in parallel)
        tasks = []
        for step in ready:
            tasks.append(_execute_step(
                runner, step, message, events, persona, person_id, course_id,
                conversation, session_id, budget,
            ))

        step_results = await asyncio.gather(*tasks, return_exceptions=True)

        for step, result in zip(ready, step_results):
            step_id = step["step_id"]
            agent = step["agent"]

            if isinstance(result, Exception):
                logger.error("Agent %s failed: %s", agent, result)
                events.append({
                    "event": "agent_result",
                    "payload": {
                        "step_id": step_id,
                        "agent": agent,
                        "output": {"error": str(result)},
                        "cost_usd": 0.0,
                        "tokens": 0,
                        "success": False,
                    },
                })
                results.append({
                    "step_id": step_id,
                    "agent": agent,
                    "output": {"error": str(result)},
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "success": False,
                })
                completed_steps[step_id] = {"error": str(result)}
            else:
                events.extend(result["events"])
                results.append(result["agent_result"])
                completed_steps[step_id] = result["agent_result"].get("output", {})
                if result.get("error") and turn_error is None:
                    turn_error = result["error"]

            remaining.remove(step)

    events.append({
        "event": "reasoning",
        "payload": {
            "step": "dispatch",
            "text": f"Dispatched {len(results)} agent(s), "
                    f"{sum(1 for r in results if r.get('success'))} succeeded",
        },
    })

    # Clients treat `error` as end-of-turn, so it must be the last event of the turn.
    if turn_error is not None:
        events.append({"event": "error", "payload": turn_error})

    return {
        **state,
        "agent_results": results,
        "events_emitted": events,
        "turn_error": turn_error,
        "budget_exceeded": bool(turn_error and turn_error["code"] == "budget_exceeded"),
    }


def _error_payload(code: str, message: str, step_id: str) -> dict[str, Any]:
    """ErrorPayload per contracts/events.md; `message` is shown to the user."""
    return {"code": code, "message": message, "retriable": False, "step_id": step_id}


def _check_permission(agent: str, persona: str) -> str | None:
    """Return a denial reason (for logs, not users) or None when the persona may use the agent."""
    if agent not in get_manifest_registry().list_agents():
        return f"agent {agent!r} has no manifest in contracts/agent-manifests.yaml"
    check = get_permission_matrix().check_agent(persona, agent)
    return None if check.allowed else check.reason


def _redact(text: str, allowed_pii: list[str]) -> str:
    return scan_and_redact(text, allowed_fields=allowed_pii).text if text else text


def _halted_step(step_id: str, agent: str, error: dict[str, Any]) -> dict[str, Any]:
    """A step that never ran: a failed agent_result plus the error that halts the turn."""
    agent_result: AgentResult = {
        "step_id": step_id,
        "agent": agent,
        "output": {"error": error["message"]},
        "cost_usd": 0.0,
        "tokens": 0,
        "success": False,
    }
    return {
        "events": [{"event": "agent_result", "payload": agent_result}],
        "agent_result": agent_result,
        "error": error,
    }


async def _execute_step(
    runner: AgentRunner,
    step: dict[str, Any],
    message: str,
    events: list[dict[str, Any]],
    persona: str = "student",
    person_id: str = "",
    course_id: str = "",
    conversation: list[dict[str, str]] | None = None,
    session_id: str = "",
    budget: BudgetTracker | None = None,
) -> dict[str, Any]:
    """Run the guardrail pass, then the agent; return events, result and any halting error.

    Permission denial or an exhausted budget skips the agent and sets `error`.
    """
    step_id = step["step_id"]
    agent = step["agent"]
    step_events: list[dict[str, Any]] = []

    denial = _check_permission(agent, persona)
    if denial is not None:
        log.warning("permission_denied", agent=agent, persona=persona, step_id=step_id,
                    reason=denial)
        return _halted_step(step_id, agent, _error_payload(
            "permission_denied",
            f"The {agent.replace('_', ' ')} assistant isn't available for the {persona} role.",
            step_id,
        ))

    if budget is not None:
        budget.add_agent_invocation()
        exceeded = budget.check()
        if exceeded.exceeded:
            log.warning("budget_exceeded", agent=agent, step_id=step_id, reason=exceeded.reason,
                        **budget.summary())
            return _halted_step(step_id, agent, _error_payload(
                "budget_exceeded", BUDGET_EXCEEDED_MESSAGE, step_id,
            ))

    allowed_pii = get_manifest_registry().get_manifest(agent).requires_pii
    message = _redact(message, allowed_pii)
    conversation = [
        {**turn, "content": _redact(turn.get("content", ""), allowed_pii)}
        for turn in (conversation or [])
    ]

    # Emit agent_start
    step_events.append({
        "event": "agent_start",
        "payload": {
            "step_id": step_id,
            "agent": agent,
            "inputs": {"message": message},
        },
    })

    # Create real-time event callback if sink is available
    async def on_agent_event(event: dict[str, Any]) -> None:
        # Fill in step_id if missing
        payload = event.get("payload", {})
        if not payload.get("step_id"):
            payload["step_id"] = step_id
        if _live_event_sink:
            await _live_event_sink(event)

    start_time = time.monotonic()
    span = span_agent(agent, step_id, persona=persona, session_id=session_id)
    with trace.use_span(span, end_on_exit=True):
        result = await runner.run(agent, {
            "message": message,
            "persona": persona,
            "person_id": person_id,
            "course_id": course_id,
            "conversation": conversation,
            "session_id": session_id,
            "_on_event": on_agent_event,
            "_budget": budget,
        })
        span.set_attribute("tokens", result.get("tokens", 0))
        span.set_attribute("success", bool(result.get("success", True)))
    elapsed_ms = (time.monotonic() - start_time) * 1000
    log.info(
        "agent_call",
        agent=agent,
        persona=persona,
        step_id=step_id,
        latency_ms=round(elapsed_ms, 1),
        tokens=result.get("tokens", 0),
        success=bool(result.get("success", True)),
    )

    # Emit tool_call and thinking events
    for tc in result.get("tool_calls", []):
        if tc.get("tool") == "__thinking__":
            step_events.append({
                "event": "thinking",
                "payload": {
                    "step_id": step_id,
                    "agent": agent,
                    "text": tc.get("result_summary", ""),
                },
            })
        else:
            step_events.append({
                "event": "agent_tool_call",
                "payload": {
                    "step_id": step_id,
                    "agent": agent,
                    "tool": tc.get("tool", "unknown"),
                    "arguments": tc.get("arguments", {}),
                    "result_summary": tc.get("result_summary", ""),
                    "latency_ms": tc.get("latency_ms", 0),
                    "success": tc.get("success", True),
                },
            })

    # Emit agent_result
    agent_result: AgentResult = {
        "step_id": step_id,
        "agent": agent,
        "output": result.get("output", {}),
        "cost_usd": result.get("cost_usd", 0.0),
        "tokens": result.get("tokens", 0),
        "success": result.get("success", True),
    }

    step_events.append({
        "event": "agent_result",
        "payload": agent_result,
    })

    error = None
    if result.get("budget_exceeded"):
        error = _error_payload("budget_exceeded", BUDGET_EXCEEDED_MESSAGE, step_id)
    return {"events": step_events, "agent_result": agent_result, "error": error}
