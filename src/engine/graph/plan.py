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


# Known multi-agent compositions from SPEC §9 scenarios
MULTI_AGENT_PATTERNS: dict[str, list[dict[str, Any]]] = {
    # Scenario 10: struggling students → study guide → send
    "identify_and_help": [
        {"agent": "early_alert",
         "input_summary": "Identify the struggling students from this course's roster and "
                          "analytics, queried in this request (earlier conversation is not "
                          "current data; person_id values come only from "
                          "roster.list_by_course); reply with a short list of them and the "
                          "risk_list block, without a methodology section"},
        {"agent": "content_generator",
         "input_summary": "Create a tailored study guide of about 500 words and save it with "
                          "content.save_draft",
         "depends_on_prev": True},
        {"agent": "communication",
         "input_summary": "Draft one supportive note to those students with "
                          "communications.draft_message, then send it with "
                          "communications.send_message (the instructor approves the send)",
         "depends_on_prev": True},
    ],
    # Scenario 8: syllabus drafting
    "syllabus_draft": [
        {"agent": "course_architect", "input_summary": "Draft course structure and outcomes"},
        {"agent": "content_generator", "input_summary": "Generate supporting materials",
         "depends_on_prev": True},
    ],
    # Scenario 4: at-risk analysis
    "risk_analysis": [
        {"agent": "early_alert", "input_summary": "Detect at-risk students"},
        {"agent": "engagement_analyst", "input_summary": "Analyze engagement trends",
         "depends_on_prev": False},
    ],
    # Scenario 2: quiz with content
    "quiz_generation": [
        {"agent": "content_generator", "input_summary": "Retrieve and organize content"},
        {"agent": "assessment", "input_summary": "Generate quiz questions",
         "depends_on_prev": True},
    ],
}


def _detect_multi_agent_pattern(action: str, agents: list[str]) -> str | None:
    """Detect if the action maps to a known multi-agent pattern."""
    if action in MULTI_AGENT_PATTERNS:
        return action
    # Heuristic: if composable_with agents are referenced
    if len(agents) > 1:
        agent_set = set(agents)
        if {"early_alert", "content_generator", "communication"} <= agent_set:
            return "identify_and_help"
        if {"course_architect", "content_generator"} <= agent_set:
            return "syllabus_draft"
        if {"early_alert", "engagement_analyst"} <= agent_set:
            return "risk_analysis"
        if {"content_generator", "assessment"} <= agent_set:
            return "quiz_generation"
    return None


async def plan_multi_agent(state: OrchestratorState) -> OrchestratorState:
    """Multi-agent plan-then-execute: produce a DAG of agent invocations.

    Used when the interpretation requires 2+ agents (SPEC §4.3).
    """
    interpretation = state.get("interpretation")
    if not interpretation:
        logger.error("Multi-agent plan called without interpretation")
        return await plan_react(state)

    action = interpretation.get("action", "unknown")
    agents = interpretation.get("parameters", {}).get("agents", [])
    pattern_name = _detect_multi_agent_pattern(action, agents)

    if pattern_name and pattern_name in MULTI_AGENT_PATTERNS:
        pattern = MULTI_AGENT_PATTERNS[pattern_name]
    else:
        # Fallback: single agent
        return await plan_react(state)

    message = state.get("current_message", "")
    steps: list[PlanStep] = []
    prev_step_id: str | None = None

    for entry in pattern:
        step_id = f"s-{uuid.uuid4().hex[:8]}"
        depends_on: list[str] = []
        if entry.get("depends_on_prev") and prev_step_id:
            depends_on = [prev_step_id]

        steps.append({
            "step_id": step_id,
            "agent": entry["agent"],
            "input_summary": entry["input_summary"],
            "depends_on": depends_on,
        })
        prev_step_id = step_id

    the_plan: Plan = {
        "strategy": "plan_then_execute",
        "steps": steps,
    }

    events: list[dict[str, Any]] = list(state.get("events_emitted", []))
    events.append({
        "event": "plan",
        "payload": {
            "strategy": "plan_then_execute",
            "steps": [
                {
                    "step_id": s["step_id"],
                    "agent": s["agent"],
                    "input_summary": s["input_summary"],
                    "depends_on": s["depends_on"],
                }
                for s in steps
            ],
            "estimated_cost_usd": 0.03 * len(steps),
            "estimated_tokens": 2000 * len(steps),
        },
    })

    agent_names = [s["agent"] for s in steps]
    events.append({
        "event": "reasoning",
        "payload": {
            "step": "plan",
            "text": f"Multi-agent plan ({pattern_name}): {' → '.join(agent_names)}",
        },
    })

    logger.info("Plan (multi-agent): pattern=%s agents=%s", pattern_name, agent_names)

    return {
        **state,
        "plan": the_plan,
        "plan_cursor": 0,
        "events_emitted": events,
    }


async def plan(state: OrchestratorState) -> OrchestratorState:
    """Unified plan step — auto-detects single vs multi-agent planning."""
    interpretation = state.get("interpretation")
    if not interpretation:
        return await plan_react(state)

    action = interpretation.get("action", "")
    agents = interpretation.get("parameters", {}).get("agents", [])
    pattern = _detect_multi_agent_pattern(action, agents)

    if pattern:
        return await plan_multi_agent(state)
    return await plan_react(state)
