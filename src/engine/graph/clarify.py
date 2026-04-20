"""Clarify step — emits a clarify event and pauses for user response (SPEC §4.1 step 2)."""

from __future__ import annotations

import logging
from typing import Any

from engine.graph.state import OrchestratorState

logger = logging.getLogger(__name__)


async def clarify(state: OrchestratorState) -> OrchestratorState:
    """Emit a clarify event and prepare state for pause.

    The orchestrator will checkpoint here. When the user responds via
    POST /api/clarify, the graph resumes at the interpret node with the
    clarification answer appended to the conversation.
    """
    reason = state.get("clarification", "Could you clarify your request?")
    interpretation = state.get("interpretation")

    # Build options from context if available
    options: list[str] | None = None
    if interpretation and interpretation.get("confidence", 0) > 0:
        options = _suggest_options(interpretation)

    # Emit clarify event
    events: list[dict[str, Any]] = list(state.get("events_emitted", []))
    events.append({
        "event": "clarify",
        "payload": {
            "question": reason,
            "reason": "The orchestrator needs more information to proceed.",
            "options": options,
        },
    })

    # Also emit a reasoning event
    events.append({
        "event": "reasoning",
        "payload": {
            "step": "clarify",
            "text": f"Asking for clarification: {reason}",
        },
    })

    logger.info("Clarify step: asking '%s'", reason)

    return {
        **state,
        "events_emitted": events,
        # Reset needs_clarification so after re-interpret we don't loop
        "needs_clarification": False,
    }


def _suggest_options(interpretation: dict[str, Any]) -> list[str] | None:
    """Generate suggested options based on partial interpretation."""
    action = interpretation.get("action", "")
    if action == "unknown":
        return [
            "I need help understanding a concept",
            "I want to create something",
            "I need to review or analyze something",
        ]
    return None
