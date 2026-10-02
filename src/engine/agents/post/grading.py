"""grading_assistant: flag short submissions and scores at a criterion's minimum."""

from __future__ import annotations

from typing import Any

from engine.agents.post._common import ToolOutput, append_note, number, results_of, short_id

SHORT_SUBMISSION_CHARS = 50
FLAGGED_CONFIDENCE_CAP = 0.6


def grading_review_flags(output: dict[str, Any], tool_outputs: list[ToolOutput]) -> dict[str, Any]:
    """Adds `flags` to each draft in `drafts` and caps a flagged draft's `confidence`.

    Drafts come from the structured output when the model returned one, otherwise only the
    note in `response_markdown` carries the flags.
    """
    body_lengths = _submission_lengths(tool_outputs)
    minimums = _criterion_minimums(tool_outputs)
    flags_by_submission: dict[str, list[str]] = {
        sid: [] for sid in body_lengths
    }
    for call in results_of(tool_outputs, "assessments.draft_grade"):
        sid = call.args.get("submission_id")
        if isinstance(sid, str):
            flags_by_submission.setdefault(sid, []).extend(
                _boundary_flags(call.args.get("scores"), minimums))

    drafts = output.get("drafts")
    if isinstance(drafts, list):
        for draft in drafts:
            if not isinstance(draft, dict) or not isinstance(draft.get("submission_id"), str):
                continue
            sid = draft["submission_id"]
            flags_by_submission.setdefault(sid, []).extend(
                _boundary_flags(draft.get("scores"), minimums))

    for sid, length in body_lengths.items():
        if length < SHORT_SUBMISSION_CHARS:
            flags_by_submission[sid].insert(
                0, f"short_submission: body is under {SHORT_SUBMISSION_CHARS} characters")
    flags_by_submission = {
        sid: list(dict.fromkeys(flags)) for sid, flags in flags_by_submission.items() if flags
    }
    if not flags_by_submission:
        return output

    if isinstance(drafts, list):
        for draft in drafts:
            if isinstance(draft, dict) and draft.get("submission_id") in flags_by_submission:
                _flag_draft(draft, flags_by_submission[draft["submission_id"]])

    lines = "; ".join(
        f"submission {short_id(sid)}: {', '.join(flags)}"
        for sid, flags in flags_by_submission.items()
    )
    append_note(output, f"Review these drafts closely — {lines}.")
    return output


def _flag_draft(draft: dict[str, Any], flags: list[str]) -> None:
    existing = draft.get("flags") if isinstance(draft.get("flags"), list) else []
    draft["flags"] = list(dict.fromkeys([*existing, *flags]))
    confidence = number(draft.get("confidence"))
    draft["confidence"] = (
        FLAGGED_CONFIDENCE_CAP if confidence is None else min(confidence, FLAGGED_CONFIDENCE_CAP)
    )


def _submission_lengths(tool_outputs: list[ToolOutput]) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for call in results_of(tool_outputs, "assessments.get_submission"):
        sid = call.value.get("id") or call.args.get("submission_id")
        body = call.value.get("body_md")
        if isinstance(sid, str) and isinstance(body, str):
            lengths[sid] = len(body.strip())
    return lengths


def _criterion_minimums(tool_outputs: list[ToolOutput]) -> dict[str, float]:
    """Lowest available points per criterion, keyed by criterion name and by id."""
    minimums: dict[str, float] = {}
    for call in results_of(tool_outputs, "assessments.get_rubric"):
        criteria = call.value.get("criteria")
        if not isinstance(criteria, list):
            continue
        for criterion in criteria:
            if not isinstance(criterion, dict):
                continue
            lowest = _criterion_minimum(criterion)
            if lowest is None:
                continue
            for key in ("name", "id"):
                if isinstance(criterion.get(key), str):
                    minimums[criterion[key]] = lowest
    return minimums


def _criterion_minimum(criterion: dict[str, Any]) -> float | None:
    explicit = number(criterion.get("min_points"))
    if explicit is not None:
        return explicit
    levels = criterion.get("levels")
    if not isinstance(levels, list):
        return None
    points = [p for p in (number(lv.get("points")) for lv in levels if isinstance(lv, dict))
              if p is not None]
    return min(points) if points else None


def _boundary_flags(scores: Any, minimums: dict[str, float]) -> list[str]:
    if not isinstance(scores, dict):
        return []
    flags = []
    for criterion, score in scores.items():
        if isinstance(score, dict):
            score = score.get("points", score.get("score"))
        value = number(score)
        lowest = minimums.get(criterion)
        if value is not None and lowest is not None and value <= lowest:
            flags.append(f"boundary_score: {criterion} at minimum")
    return flags
