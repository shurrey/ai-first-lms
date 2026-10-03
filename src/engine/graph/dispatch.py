"""Dispatch step — execute the plan by invoking sub-agents (SPEC §4.1 step 4).

Guardrail layering: dispatch checks only whether the persona may use the agent at all. Every
other check (budget, outgoing-prompt PII, tool permission and scope, tool-result PII and
injection wrapping) runs in the ToolGateway, reached through the runner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine

from opentelemetry import trace

from engine.agents.runner import EMITTED_LIVE, AgentRunner, ClaudeAgentRunner
from engine.auth.models import AuthContext
from engine.graph.interpret import ROUTABLE_AGENTS
from engine.graph.state import AgentResult, OrchestratorState
from engine.guardrails.budget import BudgetTracker
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.guardrails.injection import wrap_user_content
from engine.guardrails.registry import get_manifest_registry, get_permission_matrix
from engine.logging_config import get_logger
from engine.telemetry import span_agent

logger = logging.getLogger(__name__)
log = get_logger(__name__)

# Per upstream step, the most of its reply and of its artifacts' JSON passed downstream.
_UPSTREAM_REPLY_CHARS = 4000
_UPSTREAM_ARTIFACT_CHARS = 4000

BUDGET_EXCEEDED_MESSAGE = (
    "This request reached the usage limit for a single turn before it finished. "
    "Try a narrower question."
)

# Module-level agent runner, replaceable for testing
_agent_runner: AgentRunner | None = None

EventSink = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


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
    requester = state.get("requester")
    budget = state.get("budget")
    auth = state.get("auth")
    gateway = state.get("tool_gateway")
    turn_id = state.get("turn_id", "")
    event_sink = state.get("event_sink")
    events: list[dict[str, Any]] = list(state.get("events_emitted", []))
    results: list[AgentResult] = list(state.get("agent_results", []))
    completed_steps: dict[str, AgentResult] = {}
    steps_by_id = {s["step_id"]: s for s in steps}
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
                runner, step, step_message(message, step, steps_by_id, completed_steps),
                events, persona, person_id, course_id,
                conversation, session_id, budget, requester,
                auth=auth, gateway=gateway, turn_id=turn_id, event_sink=event_sink,
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
                failed: AgentResult = {
                    "step_id": step_id,
                    "agent": agent,
                    "output": {"error": str(result)},
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "success": False,
                }
                results.append(failed)
                completed_steps[step_id] = failed
            else:
                events.extend(result["events"])
                results.append(result["agent_result"])
                completed_steps[step_id] = result["agent_result"]
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


def step_message(
    message: str,
    step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]],
    completed: dict[str, AgentResult],
) -> str:
    """The message a plan step's agent receives: the user's message, plus in a multi-step plan
    its part of the plan, and for a step with dependencies the outputs of every step it depends
    on, directly or not, wrapped as user content (spec.md §14.5)."""
    if len(steps_by_id) < 2:
        return message
    upstream = _ancestors(step, steps_by_id)
    task = step.get("input_summary", "")
    if not upstream:
        return (f"{message}\n\nYour part of this plan: {task}. Other steps of the plan handle "
                "the rest of the request, so do only your part.")
    sections = [_upstream_section(completed[sid]) for sid in upstream if sid in completed]
    return (
        f"{message}\n\n"
        f"Your part of this plan: {task}\n\n"
        "Results from earlier steps of this plan follow. Use them instead of looking the "
        "same data up again. Still make the tool calls your part needs to save, draft or "
        "send anything; nothing is saved or sent unless you call the tool.\n\n"
        + "\n\n".join(sections)
    )


def _ancestors(step: dict[str, Any], steps_by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Step ids `step` depends on transitively, in plan order."""
    seen: set[str] = set()
    pending = list(step.get("depends_on", []))
    while pending:
        sid = pending.pop()
        if sid in seen or sid not in steps_by_id:
            continue
        seen.add(sid)
        pending.extend(steps_by_id[sid].get("depends_on", []))
    return [sid for sid in steps_by_id if sid in seen]


def _upstream_section(result: AgentResult) -> str:
    agent = result.get("agent", "unknown")
    if not result.get("success", False):
        return f"[{agent}] did not complete this step."
    output = result.get("output", {})
    reply = str(output.get("response_markdown") or output.get("content_md") or "")
    parts = [wrap_user_content(_clip(reply, _UPSTREAM_REPLY_CHARS), f"step.{agent}")]
    artifacts = result.get("artifacts") or []
    if artifacts:
        data = json.dumps([{"type": a["type"], "data": a["data"]} for a in artifacts],
                          default=str)
        parts.append(wrap_user_content(_clip(data, _UPSTREAM_ARTIFACT_CHARS),
                                       f"step.{agent}.artifacts"))
    return f"[{agent}]\n" + "\n".join(parts)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " [truncated]"


def _error_payload(code: str, message: str, step_id: str) -> dict[str, Any]:
    """ErrorPayload per contracts/events.md; `message` is shown to the user."""
    return {"code": code, "message": message, "retriable": False, "step_id": step_id}


def _check_permission(agent: str, persona: str) -> str | None:
    """Return a denial reason (for logs, not users) or None when the persona may use the agent."""
    if agent not in ROUTABLE_AGENTS:
        return f"agent {agent!r} is not routable from a user turn"
    if agent not in get_manifest_registry().list_agents():
        return f"agent {agent!r} has no manifest in contracts/agent-manifests.yaml"
    check = get_permission_matrix().check_agent(persona, agent)
    return None if check.allowed else check.reason


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
    requester: dict[str, str] | None = None,
    *,
    auth: AuthContext | None = None,
    gateway: ToolGateway | None = None,
    turn_id: str = "",
    event_sink: EventSink | None = None,
) -> dict[str, Any]:
    """Check the agent permission, then run the agent; return events, result and any
    halting error. A denial skips the agent; an exhausted budget or an unanswered approval
    (reported by the runner) sets `error`. Without `auth` the agent runs but the gateway
    denies every tool call.
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

    agent_start = {
        "event": "agent_start",
        "payload": {
            "step_id": step_id,
            "agent": agent,
            "inputs": {"message": message},
        },
    }
    # Sent live so it precedes the agent's own live tool, thinking and approval events.
    if event_sink is not None:
        await event_sink(agent_start)
    else:
        step_events.append(agent_start)

    # Create real-time event callback if sink is available
    async def on_agent_event(event: dict[str, Any]) -> None:
        # Fill in step_id if missing
        payload = event.get("payload", {})
        if not payload.get("step_id"):
            payload["step_id"] = step_id
        if event_sink is not None:
            await event_sink(event)

    ai_action_ids: list[str] = []
    start_time = time.monotonic()
    span = span_agent(agent, step_id, persona=persona, session_id=session_id)
    with trace.use_span(span, end_on_exit=True):
        inputs: dict[str, Any] = {
            "message": message,
            "persona": persona,
            "person_id": person_id,
            "course_id": course_id,
            "conversation": conversation or [],
            "session_id": session_id,
            "_on_event": on_agent_event if event_sink is not None else None,
            "_tool_context": GatewayContext(
                auth=auth, session_id=session_id, turn_id=turn_id, step_id=step_id,
                budget=budget, course_id=course_id,
                # approval_request must reach the client live; with no sink, gated tools deny
                emit=on_agent_event if event_sink is not None else None,
                ai_action_ids=ai_action_ids,
            ),
        }
        if gateway is not None:
            inputs["_gateway"] = gateway
        if requester:
            inputs["requester"] = requester
        result = await runner.run(agent, inputs)
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

    # Tool-call, thinking and guardrail events the runner did not already send live
    for tc in result.get("tool_calls", []):
        if tc.get(EMITTED_LIVE):
            continue
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
            if tc.get("guardrail"):
                step_events.append({
                    "event": "guardrail",
                    "payload": {**tc["guardrail"], "step_id": step_id},
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

    # The artifacts reach the client in `final` only; agent_result keeps its contract fields.
    step_events.append({
        "event": "agent_result",
        "payload": dict(agent_result),
    })
    if "artifacts" in result:
        agent_result["artifacts"] = list(result["artifacts"])
    if ai_action_ids:
        agent_result["ai_action_ids"] = list(ai_action_ids)

    error = None
    if result.get("budget_exceeded"):
        error = _error_payload("budget_exceeded", BUDGET_EXCEEDED_MESSAGE, step_id)
    elif result.get("halt"):
        error = _error_payload(result["halt"]["code"], result["halt"]["message"], step_id)
    return {"events": step_events, "agent_result": agent_result, "error": error}
