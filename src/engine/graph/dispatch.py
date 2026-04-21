"""Dispatch step — execute the plan by invoking sub-agents (SPEC §4.1 step 4)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from engine.agents.runner import AgentRunner, ClaudeAgentRunner
from engine.graph.state import AgentResult, OrchestratorState

logger = logging.getLogger(__name__)

# Module-level agent runner, replaceable for testing
_agent_runner: AgentRunner | None = None


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
    conversation = state.get("conversation", [])
    events: list[dict[str, Any]] = list(state.get("events_emitted", []))
    results: list[AgentResult] = list(state.get("agent_results", []))
    completed_steps: dict[str, dict[str, Any]] = {}

    # Group steps by dependency layer for execution
    remaining = list(steps)
    while remaining:
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
            tasks.append(_execute_step(runner, step, message, events, persona, person_id, course_id, conversation))

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

            remaining.remove(step)

    events.append({
        "event": "reasoning",
        "payload": {
            "step": "dispatch",
            "text": f"Dispatched {len(results)} agent(s), "
                    f"{sum(1 for r in results if r.get('success'))} succeeded",
        },
    })

    return {
        **state,
        "agent_results": results,
        "events_emitted": events,
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
) -> dict[str, Any]:
    """Execute a single plan step and return events + result."""
    step_id = step["step_id"]
    agent = step["agent"]
    step_events: list[dict[str, Any]] = []

    # Emit agent_start
    step_events.append({
        "event": "agent_start",
        "payload": {
            "step_id": step_id,
            "agent": agent,
            "inputs": {"message": message},
        },
    })

    start_time = time.monotonic()
    result = await runner.run(agent, {
        "message": message,
        "persona": persona,
        "person_id": person_id,
        "course_id": course_id,
        "conversation": conversation or [],
    })
    elapsed_ms = (time.monotonic() - start_time) * 1000

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

    return {"events": step_events, "agent_result": agent_result}
