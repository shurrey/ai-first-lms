"""Conditional edge functions for the orchestrator state machine."""

from __future__ import annotations

from typing import Literal

from engine.graph.state import OrchestratorState


def should_clarify(state: OrchestratorState) -> Literal["clarify", "plan"]:
    """After interpret: route to clarify if ambiguous, otherwise to plan."""
    if state.get("needs_clarification"):
        return "clarify"
    return "plan"
