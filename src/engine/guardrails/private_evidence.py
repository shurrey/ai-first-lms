"""Keeps a learner's private evidence (practice attempts, spec.md §12.5) from other viewers.

roster.get_student_context returns the learner's recent evidence to any permitted viewer.
Only rows marked `course` or `program` visibility reach anyone but the learner; a row with
no visibility is treated as private.
"""

from __future__ import annotations

import json
from typing import Any

STUDENT_CONTEXT_TOOL = "roster.get_student_context"
SHARED_VISIBILITY = frozenset({"course", "program"})


def is_shared(evidence: Any) -> bool:
    return (isinstance(evidence, dict) and evidence.get("visibility") in SHARED_VISIBILITY
            and evidence.get("source") != "practice")


def withhold_private(context: dict[str, Any], person_id: Any, viewer_id: str | None
                     ) -> dict[str, Any]:
    """A student-context result with only shared `recent_evidence`, unless the viewer is the
    learner."""
    rows = context.get("recent_evidence")
    if str(person_id) == str(viewer_id) or not isinstance(rows, list):
        return context
    return {**context, "recent_evidence": [e for e in rows if is_shared(e)]}


def withhold_private_in_result(tool: str, args: dict[str, Any], raw: str,
                               viewer_id: str | None) -> str:
    """`raw` (a tool result) with `withhold_private` applied to a student-context result;
    any other tool's result, or one that is not a JSON object, is returned unchanged."""
    if tool != STUDENT_CONTEXT_TOOL:
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw
    if not isinstance(parsed, dict):
        return raw
    kept = withhold_private(parsed, args.get("person_id"), viewer_id)
    return raw if kept is parsed else json.dumps(kept, ensure_ascii=False, default=str)
