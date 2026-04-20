"""Plan step — produces a DAG of sub-agent invocations (SPEC §4.3)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from engine.graph.state import OrchestratorState, Plan, PlanStep

logger = logging.getLogger(__name__)


async def plan_react(state: OrchestratorState) -> OrchestratorState:
    """Single-agent ReAct plan: invoke one agent with the user's intent.

    Used when the interpretation maps to exactly one agent (SPEC §4.3).
    """
    interpretation = state.get("interpretation")
    if not interpretation:
        logger.error("Plan step called without interpretation")
        return {
            **state,
            "plan": {
                "strategy": "react",
                "steps": [],
            },
            "plan_cursor": 0,
        }

    agent = interpretation.get("agent", "tutor")
    action = interpretation.get("action", "unknown")
    params = interpretation.get("parameters", {})
    message = state.get("current_message", "")

    step_id = f"s-{uuid.uuid4().hex[:8]}"
    step: PlanStep = {
        "step_id": step_id,
        "agent": agent,
        "input_summary": f"{action}: {message}",
        "depends_on": [],
    }

    the_plan: Plan = {
        "strategy": "react",
        "steps": [step],
    }

    # Emit plan event
    events: list[dict[str, Any]] = list(state.get("events_emitted", []))
    events.append({
        "event": "plan",
        "payload": {
            "strategy": "react",
            "steps": [
                {
                    "step_id": step_id,
                    "agent": agent,
                    "input_summary": f"{action}: {message}",
                    "depends_on": [],
                }
            ],
            "estimated_cost_usd": 0.01,
            "estimated_tokens": 1000,
        },
    })

    events.append({
        "event": "reasoning",
        "payload": {
            "step": "plan",
            "text": f"Single-agent plan: invoking {agent} for {action}",
        },
    })

    logger.info("Plan (react): agent=%s action=%s", agent, action)

    return {
        **state,
        "plan": the_plan,
        "plan_cursor": 0,
        "events_emitted": events,
    }
