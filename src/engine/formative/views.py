"""Pure shaping of formative-loop rows into the api.openapi.yaml assessment schemas."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from engine.formative.store import CriterionRow, DecisionRow, SubmissionRow

FeedbackStatus = Literal["pending", "awaiting_release", "released", "suppressed", "failed",
                         "none"]
ImprovementView = Literal["self", "full", "summary", "aggregate"]

REJECTED = "rejected"
EDITED = "edited"


def recorded(criteria: Iterable[CriterionRow]) -> list[CriterionRow]:
    """Criteria the feedback agent scored and whose ai_actions row is linked."""
    return [c for c in criteria if c.ai_score is not None and c.ai_action_id is not None]


def criterion_decisions(criterion: CriterionRow, decisions: dict[str, list[DecisionRow]]
                        ) -> list[DecisionRow]:
    """Decisions on this criterion, oldest first. One criterion_feedback action covers every
    criterion saved together, so each decision names its criterion in `diff.criterion_id`;
    a decision without one applies to all of them."""
    return [d for d in decisions.get(criterion.ai_action_id or "", [])
            if (d.diff or {}).get("criterion_id") in (None, criterion.criterion_id)]


def is_rejected(criterion: CriterionRow, decisions: dict[str, list[DecisionRow]]) -> bool:
    found = criterion_decisions(criterion, decisions)
    return bool(found) and found[-1].decision == REJECTED


def feedback_status(submission: SubmissionRow, criteria: list[CriterionRow],
                    decisions: dict[str, list[DecisionRow]], *, failed: bool = False
                    ) -> FeedbackStatus:
    """`failed` says the submission has an undismissed failed feedback run: one that saved
    nothing, or saved feedback whose automatic release was refused."""
    if submission.status != "draft":
        return "none"
    scored = recorded(criteria)
    if not scored:
        return "failed" if failed else "pending"
    if any(c.released_at is not None for c in scored):
        return "released"
    if failed:
        return "failed"
    if all(is_rejected(c, decisions) for c in scored):
        return "suppressed"
    return "awaiting_release"


def awaiting(criteria: list[CriterionRow], decisions: dict[str, list[DecisionRow]]
             ) -> list[CriterionRow]:
    """Recorded criteria not yet released or suppressed."""
    return [c for c in recorded(criteria)
            if c.released_at is None and not is_rejected(c, decisions)]


def visible_to_learner(criterion: CriterionRow, decisions: dict[str, list[DecisionRow]]
                       ) -> bool:
    return criterion.released_at is not None and not is_rejected(criterion, decisions)


def _saved_next_step(criterion: CriterionRow, output: dict[str, Any]) -> str | None:
    """The agent's next step from the action output: a `criteria` list (one action per save)
    or a top-level `next_step`."""
    for item in output.get("criteria") or []:
        if isinstance(item, dict) and item.get("criterion_id") == criterion.criterion_id:
            step = item.get("next_step")
            return step if isinstance(step, str) else None
    step = output.get("next_step")
    return step if isinstance(step, str) else None


def next_step(criterion: CriterionRow, output: dict[str, Any],
              decisions: dict[str, list[DecisionRow]]) -> str | None:
    """The instructor's latest edit of the next step, else the agent's. Score and rationale
    edits are applied to criterion_scores by the release itself; the next step is not stored
    there."""
    for decision in reversed(criterion_decisions(criterion, decisions)):
        if decision.decision != EDITED:
            continue
        edited = ((decision.diff or {}).get("fields") or {}).get("next_step")
        if isinstance(edited, dict) and isinstance(edited.get("after"), str):
            return edited["after"]
    return _saved_next_step(criterion, output)


def level_label(levels: list[dict[str, Any]], score: int | None) -> str | None:
    if score is None:
        return None
    for level in levels:
        if isinstance(level, dict) and level.get("score") == score:
            label = level.get("label")
            return label if isinstance(label, str) else None
    return None


def criterion_feedback(criterion: CriterionRow, output: dict[str, Any],
                       decisions: dict[str, list[DecisionRow]], *, hide_score: bool
                       ) -> dict[str, Any]:
    score = None if hide_score else criterion.ai_score
    return {
        "criterion_id": criterion.criterion_id,
        "criterion_key": criterion.key,
        "description": criterion.description,
        "ai_score": score,
        "level_label": level_label(criterion.levels, score),
        "ai_rationale": criterion.ai_rationale,
        "evidence_spans": criterion.ai_evidence_spans,
        "next_step": next_step(criterion, output, decisions),
        "final_score": criterion.final_score,
        "ai_action_id": criterion.ai_action_id,
        "released_at": criterion.released_at.isoformat() if criterion.released_at else None,
    }


def changed_fields(criterion: CriterionRow, output: dict[str, Any],
                   decisions: dict[str, list[DecisionRow]], edit: dict[str, Any]
                   ) -> dict[str, Any]:
    """The parts of an instructor's edit (ai_score, ai_rationale, next_step; None = not
    edited) that differ from the feedback as it stands."""
    current = {"ai_score": criterion.ai_score, "ai_rationale": criterion.ai_rationale,
               "next_step": next_step(criterion, output, decisions)}
    return {k: v for k, v in edit.items()
            if k in current and v is not None and v != current[k]}


# --- version chains ---------------------------------------------------------------------


def chain_of(versions: list[SubmissionRow], submission_id: str) -> list[SubmissionRow]:
    """The revision chain through `submission_id`, oldest first: its ancestors, then its
    latest-version descendant at each step. Empty when the id is not in `versions`."""
    by_id = {v.id: v for v in versions}
    if submission_id not in by_id:
        return []
    chain = [by_id[submission_id]]
    seen = {submission_id}
    while chain[0].parent_id in by_id and chain[0].parent_id not in seen:
        parent = by_id[chain[0].parent_id]  # type: ignore[index]
        seen.add(parent.id)
        chain.insert(0, parent)
    while True:
        children = [v for v in versions if v.parent_id == chain[-1].id and v.id not in seen]
        if not children:
            return chain
        child = max(children, key=lambda v: (v.version, v.submitted_at, v.id))
        seen.add(child.id)
        chain.append(child)


def version_scores(chain: list[SubmissionRow], criteria: dict[str, list[CriterionRow]],
                   visible: Any) -> list[list[dict[str, Any]]]:
    """Per version, the criteria `visible(criterion)` admits with score and the change from
    the previous version's visible score (null on the first or when either is missing).
    `visible` returns the score to show, or False to leave the criterion out."""
    previous: dict[str, int | None] = {}
    out: list[list[dict[str, Any]]] = []
    for index, version in enumerate(chain):
        rows: list[dict[str, Any]] = []
        current: dict[str, int | None] = {}
        for criterion in criteria.get(version.id, []):
            shown = visible(criterion)
            if shown is False:
                continue
            score = shown if isinstance(shown, int) and not isinstance(shown, bool) else None
            current[criterion.criterion_id] = score
            before = previous.get(criterion.criterion_id)
            delta = score - before if index and score is not None and before is not None \
                else None
            rows.append({"criterion_id": criterion.criterion_id,
                         "criterion_key": criterion.key, "score": score, "delta": delta})
        previous = {**previous, **current}
        out.append(rows)
    return out


# --- improvement --------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _trajectory(raw: dict[str, Any], *, with_points: bool) -> dict[str, Any]:
    points = []
    for point in raw.get("points") or [] if with_points else []:
        if not isinstance(point, dict):
            continue
        points.append({"submission_id": point.get("submission_id"),
                       "version": point.get("version"), "status": point.get("status"),
                       "score": _int(point.get("score")),
                       "submitted_at": point.get("submitted_at") or point.get("at")})
    delta = raw.get("latest_delta", raw.get("delta"))
    return {"criterion_id": raw.get("criterion_id"), "points": points,
            "latest_delta": _int(delta), "flag": raw.get("flag")}


def _aggregate(students: list[dict[str, Any]], criterion_ids: list[str]
               ) -> list[dict[str, Any]]:
    out = []
    for cid in criterion_ids:
        deltas: list[int] = []
        flags: dict[str, int] = {}
        n = 0
        for student in students:
            for t in student["trajectories"]:
                if t["criterion_id"] != cid:
                    continue
                n += 1
                if t["latest_delta"] is not None:
                    deltas.append(t["latest_delta"])
                flag = t["flag"] or "none"
                flags[flag] = flags.get(flag, 0) + 1
        out.append({"criterion_id": cid, "n_students": n,
                    "mean_delta": round(sum(deltas) / len(deltas), 3) if deltas else None,
                    "flag_counts": flags})
    return out


def improvement(raw: dict[str, Any], course_id: str, *, view: ImprovementView,
                descriptions: dict[str, CriterionRow], names: dict[str, str],
                students_allowed: frozenset[str] | None) -> dict[str, Any]:
    """The Improvement schema from `assessments.get_improvement` output.

    `students_allowed` None keeps every student. `summary` drops trajectory points,
    `aggregate` drops students and `self` drops the aggregate, which is the tool's when given.
    """
    criteria = []
    for item in raw.get("criteria") or []:
        if not isinstance(item, dict) or not isinstance(item.get("criterion_id"), str):
            continue
        meta = descriptions.get(item["criterion_id"])
        criteria.append({
            "criterion_id": item["criterion_id"],
            "criterion_key": item.get("key") or (meta.key if meta else ""),
            "description": meta.description if meta else (item.get("description") or ""),
            "target_score": _int(item.get("target_score")),
        })
    students = []
    for item in raw.get("students") or []:
        sid = item.get("student_id") if isinstance(item, dict) else None
        if not isinstance(sid, str):
            continue
        if students_allowed is not None and sid not in students_allowed:
            continue
        students.append({
            "student_id": sid,
            "display_name": names.get(sid) or str(item.get("display_name") or ""),
            "trajectories": [_trajectory(t, with_points=view != "summary")
                             for t in item.get("trajectories") or [] if isinstance(t, dict)],
        })
    body: dict[str, Any] = {"course_id": course_id, "criteria": criteria,
                            "students": [] if view == "aggregate" else students}
    if view != "self":
        given = raw.get("aggregate")
        body["aggregate"] = (_given_aggregate(given) if isinstance(given, list)
                             else _aggregate(students, [c["criterion_id"] for c in criteria]))
    return body


def _given_aggregate(items: list[Any]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("criterion_id"), str):
            continue
        flags = item.get("flag_counts")
        mean = item.get("mean_delta")
        out.append({"criterion_id": item["criterion_id"],
                    "n_students": _int(item.get("n_students")) or 0,
                    "mean_delta": mean if isinstance(mean, (int, float))
                    and not isinstance(mean, bool) else None,
                    "flag_counts": {str(k): v for k, v in flags.items() if _int(v) is not None}
                    if isinstance(flags, dict) else {}})
    return out
