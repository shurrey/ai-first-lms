"""assessment: warn when a question's Bloom level is outside its difficulty's usual range."""

from __future__ import annotations

from typing import Any

from engine.agents.post._common import ToolOutput, append_note, results_of

BLOOM_RANGE_BY_DIFFICULTY: dict[str, tuple[str, ...]] = {
    "intro": ("remember", "understand"),
    "moderate": ("apply", "analyze"),
    "advanced": ("evaluate", "create"),
}


def assessment_bloom_range(
    output: dict[str, Any], tool_outputs: list[ToolOutput]
) -> dict[str, Any]:
    """Adds a warning to `warnings` per out-of-range question.

    Questions come from the structured `questions` output when present, else from the
    arguments of `assessments.create_question` calls. `mixed` difficulty is never flagged.
    """
    questions = output.get("questions")
    if not isinstance(questions, list) or not questions:
        questions = [call.args for call in results_of(tool_outputs, "assessments.create_question")]
    new_warnings = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        difficulty = str(question.get("difficulty") or "").lower()
        bloom = str(question.get("bloom_level") or "").lower()
        allowed = BLOOM_RANGE_BY_DIFFICULTY.get(difficulty)
        if allowed and bloom and bloom not in allowed:
            new_warnings.append(
                f"Question {index}: Bloom level '{bloom}' is outside the usual range for "
                f"{difficulty} difficulty ({', '.join(allowed)})."
            )
    if not new_warnings:
        return output
    existing = output.get("warnings")
    warnings = list(existing) if isinstance(existing, list) else []
    warnings.extend(w for w in new_warnings if w not in warnings)
    output["warnings"] = warnings
    append_note(output, " ".join(new_warnings))
    return output
