"""Skeleton node functions for the orchestrator state machine.

Each node is a no-op stub that will be replaced with real logic in later tasks
(T-E-006 through T-E-011).
"""

from __future__ import annotations

from engine.graph.state import OrchestratorState


async def interpret(state: OrchestratorState) -> OrchestratorState:
    """Extract structured intent from user message. (Stub — T-E-006.)"""
    return {
        **state,
        "interpretation": {
            "action": "explain",
            "agent": "tutor",
            "parameters": {},
            "confidence": 1.0,
        },
        "needs_clarification": False,
    }


async def clarify(state: OrchestratorState) -> OrchestratorState:
    """Ask clarifying question when intent is ambiguous. (Stub — T-E-007.)"""
    return {
        **state,
        "clarification": "Could you be more specific?",
    }


async def plan(state: OrchestratorState) -> OrchestratorState:
    """Produce a DAG of sub-agent invocations. (Stub — T-E-008/009.)"""
    agent = "tutor"
    if state.get("interpretation"):
        agent = state["interpretation"].get("agent", "tutor")  # type: ignore[union-attr]

    return {
        **state,
        "plan": {
            "strategy": "react",
            "steps": [
                {
                    "step_id": "s1",
                    "agent": agent,
                    "input_summary": state.get("current_message", ""),
                    "depends_on": [],
                }
            ],
        },
        "plan_cursor": 0,
    }


async def dispatch(state: OrchestratorState) -> OrchestratorState:
    """Execute the plan by invoking sub-agents. (Stub — T-E-010.)"""
    return {
        **state,
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "tutor",
                "output": {"response_markdown": "This is a stub response."},
                "cost_usd": 0.0,
                "tokens": 0,
                "success": True,
            }
        ],
    }


async def synthesize(state: OrchestratorState) -> OrchestratorState:
    """Combine sub-agent outputs into final response. (Stub — T-E-011.)"""
    results = state.get("agent_results", [])
    if results:
        answer = results[0].get("output", {}).get("response_markdown", "No response.")
    else:
        answer = "No response."

    return {
        **state,
        "final_answer": answer,
    }
