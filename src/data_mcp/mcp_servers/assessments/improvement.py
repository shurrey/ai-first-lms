"""Deterministic formative-loop rules (spec.md §7.3): criterion targets, trajectory flags and
the weakness detector. Pure functions over already-visible scores; no database, no model."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

WEAKNESS_WINDOW_DEFAULT = 3
WEAKNESS_WINDOW_MIN = 2
WEAKNESS_WINDOW_MAX = 10
WEAKNESS_MIN_BELOW = 2

PLATEAUED = "plateaued"
REGRESSED = "regressed"
READY = "ready_for_summative"


@dataclass(frozen=True)
class Observation:
    """One visible score of one criterion on one submission version."""

    submission_id: str
    person_id: str
    version: int
    status: str
    submitted_at: datetime
    criterion_id: str
    key: str
    score: int
    target: int | None
    outcome_nodes: tuple[str, ...] = field(default_factory=tuple)


def target_score(levels: Any) -> int | None:
    """The score that counts as "at target": the level labelled Proficient, else the
    second-highest level (the highest when there are only two). None without levels."""
    if not isinstance(levels, list):
        return None
    scores: list[int] = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        score = level.get("score")
        if isinstance(score, bool) or not isinstance(score, int):
            continue
        if str(level.get("label", "")).strip().lower() == "proficient":
            return score
        scores.append(score)
    distinct = sorted(set(scores))
    if not distinct:
        return None
    return distinct[-2] if len(distinct) >= 3 else distinct[-1]


def trajectory_flag(scores: Sequence[int], target: int | None, latest_status: str) -> str | None:
    """Flag for one student × criterion trajectory, scores oldest first.

    regressed: the latest score is below the one before it. plateaued: the latest equals the
    one before it and is below target. ready_for_summative: the latest is a draft at or above
    target. Checked in that order.
    """
    if not scores:
        return None
    last = scores[-1]
    if len(scores) >= 2 and last < scores[-2]:
        return REGRESSED
    if len(scores) >= 2 and last == scores[-2] and target is not None and last < target:
        return PLATEAUED
    if target is not None and last >= target and latest_status == "draft":
        return READY
    return None


def _newest_first(observations: Iterable[Observation]) -> list[Observation]:
    return sorted(observations, key=lambda o: (o.submitted_at, o.version, o.submission_id),
                  reverse=True)


def detect_weaknesses(observations: Iterable[Observation], window: int) -> list[dict[str, Any]]:
    """Criteria below target on at least two of a student's last `window` scored submissions.

    Criteria are grouped by key across the course's rubrics, so a recurring weakness on
    "evidence" is found across assignments. Returns one entry per key, sorted by key;
    `criterion_id` is the newest submission's criterion and `last_scores` is newest first.
    """
    by_key: dict[str, list[Observation]] = {}
    for obs in observations:
        by_key.setdefault(obs.key, []).append(obs)
    weaknesses: list[dict[str, Any]] = []
    for key in sorted(by_key):
        recent = _newest_first(by_key[key])[:window]
        below = sum(1 for o in recent if o.target is not None and o.score < o.target)
        if below < WEAKNESS_MIN_BELOW:
            continue
        outcomes: list[str] = []
        for obs in recent:
            outcomes.extend(n for n in obs.outcome_nodes if n not in outcomes)
        weaknesses.append({
            "criterion_id": recent[0].criterion_id,
            "key": key,
            "outcome_nodes": outcomes,
            "below_target_count": below,
            "window": window,
            "last_scores": [o.score for o in recent],
            "target_score": recent[0].target,
        })
    return weaknesses
