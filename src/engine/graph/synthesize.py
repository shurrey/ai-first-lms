"""Synthesize step — combine sub-agent outputs into final response (SPEC §4.1 step 5)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from engine.graph.state import AgentResult, OrchestratorState

logger = logging.getLogger(__name__)


async def synthesize(state: OrchestratorState) -> OrchestratorState:
    """Combine agent results into a final answer and emit a final event."""
    results = state.get("agent_results", [])
    start_time = state.get("_start_time", time.monotonic())
    events: list[dict[str, Any]] = list(state.get("events_emitted", []))

    follow_ups: list[str] = []
    if not results:
        answer = "I wasn't able to produce a response. Please try again."
        artifacts: list[dict[str, Any]] = []
    elif len(results) == 1:
        answer, artifacts, follow_ups = _synthesize_single(results[0])
    else:
        answer, artifacts = _synthesize_multi(results)

    # Calculate totals
    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    total_tokens = sum(r.get("tokens", 0) for r in results)
    wall_time_ms = (time.monotonic() - start_time) * 1000

    # Emit reasoning event
    events.append({
        "event": "reasoning",
        "payload": {
            "step": "synthesize",
            "text": f"Synthesizing response from {len(results)} agent(s)",
        },
    })

    # Emit final event per contracts/events.md
    events.append({
        "event": "final",
        "payload": {
            "answer_markdown": answer,
            "artifacts": artifacts,
            "follow_ups": follow_ups,
            "cost_usd": total_cost,
            "tokens": total_tokens,
            "wall_time_ms": wall_time_ms,
        },
    })

    return {
        **state,
        "final_answer": answer,
        "cost_usd": state.get("cost_usd", 0.0) + total_cost,
        "tokens": state.get("tokens", 0) + total_tokens,
        "events_emitted": events,
    }


def _synthesize_single(result: AgentResult) -> tuple[str, list[dict[str, Any]], list[str]]:
    """For single-agent results, pass through with minimal wrapping."""
    output = result.get("output", {})
    answer = output.get("response_markdown") or output.get("content_md") or ""

    # If no markdown response, try to create a readable summary
    if not answer:
        answer = _format_output(output)

    artifacts = _extract_artifacts(result)
    follow_ups = output.get("follow_ups", [])
    return answer, artifacts, follow_ups


def _synthesize_multi(results: list[AgentResult]) -> tuple[str, list[dict[str, Any]]]:
    """For multi-agent results, combine into a coherent response."""
    sections: list[str] = []
    all_artifacts: list[dict[str, Any]] = []

    for result in results:
        agent = result.get("agent", "unknown")
        output = result.get("output", {})
        success = result.get("success", False)

        if not success:
            sections.append(f"**{agent}**: Unable to complete this step.")
            continue

        text = output.get("response_markdown") or output.get("content_md") or ""
        if not text:
            text = _format_output(output)

        if text:
            sections.append(text)

        all_artifacts.extend(_extract_artifacts(result))

    answer = "\n\n---\n\n".join(sections) if sections else "No results produced."
    return answer, all_artifacts


def _extract_artifacts(result: AgentResult) -> list[dict[str, Any]]:
    """Extract structured artifacts from agent output."""
    output = result.get("output", {})
    artifacts: list[dict[str, Any]] = []
    agent = result.get("agent", "unknown")

    # Map agent outputs to artifact types
    artifact_mapping = {
        "drafts": "rubric_grades",
        "questions": "quiz",
        "charts": "chart",
        "at_risk": "risk_list",
        "audit": "degree_audit",
        "report": "wcag_report",
        "send_ready_payload": "message",
        "content_md": "content_draft",
        "path_visualization": "learning_path",
    }

    for key, artifact_type in artifact_mapping.items():
        if key in output and output[key]:
            artifacts.append({
                "artifact_id": f"{agent}-{key}",
                "type": artifact_type,
                "data": output[key] if isinstance(output[key], dict) else {"items": output[key]},
            })

    return artifacts


def _format_output(output: dict[str, Any]) -> str:
    """Create a readable markdown summary from structured output."""
    parts = []
    for key, value in output.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list) and value:
            parts.append(f"**{key.replace('_', ' ').title()}:** {len(value)} items")
    return "\n\n".join(parts) if parts else ""
