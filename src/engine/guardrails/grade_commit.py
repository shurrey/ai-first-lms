"""What an instructor must supply to commit a grade (spec.md §7.4, §7.9).

`assessments.commit_grade` runs only with the approver's own `final_scores` for every
criterion and a non-empty `holistic_md` closing comment. The agent can never supply them: the
gateway drops them from the model's call, so they can only arrive in the approval edit.
"""

from __future__ import annotations

import re
from typing import Any

COMMIT_TOOL = "assessments.commit_grade"
# Fields only the approver may supply on a commit; the model's values are dropped.
INSTRUCTOR_INPUTS = frozenset({"final_scores", "holistic_md", "feedback"})
MAX_COMMENT_CHARS = 20_000

_NON_WORD = re.compile(r"[^a-z0-9]+")


class CommitIncompleteError(ValueError):
    """The commit lacks an instructor input; the message is user-safe."""


def normalize_key(key: str) -> str:
    """'Writing Mechanics', 'writing_mechanics' and 'writing-mechanics' are one criterion."""
    return _NON_WORD.sub("_", key.lower()).strip("_")


def without_instructor_inputs(args: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k not in INSTRUCTOR_INPUTS}


def criterion_keys(draft_scores: Any, rubric: dict[str, Any] | None) -> list[str]:
    """The criteria a commit must score: those the draft scored plus every rubric criterion
    (by `key`, else `name`), in first-seen order, spelled as the draft spells them."""
    keys: dict[str, str] = {}
    for key in draft_scores if isinstance(draft_scores, dict) else {}:
        if isinstance(key, str) and normalize_key(key):
            keys.setdefault(normalize_key(key), key)
    criteria = rubric.get("criteria") if rubric else None
    for item in criteria if isinstance(criteria, list) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("key") or item.get("name")
        if isinstance(name, str) and normalize_key(name):
            keys.setdefault(normalize_key(name), name)
    return list(keys.values())


def _is_score(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_commit(args: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """`args` with `final_scores` re-keyed to the spelling in `required`; raises
    CommitIncompleteError unless every required criterion has a whole-number score and the
    closing comment is non-empty."""
    if not required:
        raise CommitIncompleteError("The rubric criteria for this grade could not be loaded, so it "
                               "can't be committed.")
    final = args.get("final_scores")
    if not isinstance(final, dict):
        raise CommitIncompleteError("Committing a grade needs your final score on every criterion "
                               "(final_scores).")
    by_norm = {normalize_key(k): k for k in required}
    scores: dict[str, int] = {}
    for key, value in final.items():
        target = by_norm.get(normalize_key(key)) if isinstance(key, str) else None
        if target is None:
            raise CommitIncompleteError(f"{key} is not a criterion of this grade.")
        if not _is_score(value):
            raise CommitIncompleteError(f"The final score for {target} must be a whole number.")
        scores[target] = value
    missing = [k for k in required if k not in scores]
    if missing:
        raise CommitIncompleteError("Committing a grade needs your final score on every criterion; "
                               f"missing: {', '.join(missing)}.")
    comment = args.get("holistic_md")
    if not isinstance(comment, str) or not comment.strip():
        raise CommitIncompleteError("Committing a grade needs your closing comment (holistic_md).")
    if len(comment) > MAX_COMMENT_CHARS:
        raise CommitIncompleteError("The closing comment is too long.")
    feedback = args.get("feedback")
    if feedback is not None and not (isinstance(feedback, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in feedback.items())):
        raise CommitIncompleteError("feedback must map criteria to text.")
    return {**args, "final_scores": scores}
