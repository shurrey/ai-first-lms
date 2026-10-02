"""advising: flag a recommended course load above the default credit cap."""

from __future__ import annotations

from typing import Any

from engine.agents.post._common import ToolOutput, append_note, number

DEFAULT_MAX_CREDITS = 15


def advising_credit_load(
    output: dict[str, Any], tool_outputs: list[ToolOutput]
) -> dict[str, Any]:
    """Adds a `credit_load` risk to `risks` when recommended credits exceed 15.

    Acts only on a structured `recommendations` list whose items carry numeric `credits`;
    recommendations are kept, since the student may have a higher approved load.
    """
    recommendations = output.get("recommendations")
    if not isinstance(recommendations, list):
        return output
    credits = [
        c for c in (number(r.get("credits")) for r in recommendations if isinstance(r, dict))
        if c is not None
    ]
    total = sum(credits)
    if total <= DEFAULT_MAX_CREDITS:
        return output
    description = (f"Recommended courses total {total:g} credits, above the usual "
                   f"{DEFAULT_MAX_CREDITS}-credit load.")
    existing = output.get("risks")
    risks = list(existing) if isinstance(existing, list) else []
    risks.append({
        "type": "credit_load",
        "description": description,
        "mitigation": "Confirm the student can take an overload, or move a course to a later term.",
    })
    output["risks"] = risks
    append_note(output, description)
    return output
