"""Shared types and helpers for the agent post-processors."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolOutput:
    """One successful tool call: arguments as executed and the redacted, unwrapped result."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    value: Any = None


def results_of(tool_outputs: list[ToolOutput], tool: str) -> Iterator[ToolOutput]:
    """Calls of `tool` whose result is a JSON object, in call order."""
    for call in tool_outputs:
        if call.tool == tool and isinstance(call.value, dict):
            yield call


def number(value: Any) -> float | None:
    """`value` as a float when it is a real number (bools excluded), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def append_note(output: dict[str, Any], note: str) -> None:
    """Append a visible note to `response_markdown`, which synthesize shows the user."""
    markdown = output.get("response_markdown")
    if isinstance(markdown, str):
        output["response_markdown"] = f"{markdown.rstrip()}\n\n> **Note:** {note}"


def short_id(value: Any) -> str:
    return str(value)[:8]
