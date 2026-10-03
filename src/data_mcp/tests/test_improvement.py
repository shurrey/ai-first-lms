"""Unit tests for the deterministic weakness detector and trajectory flags (spec.md §7.3)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_mcp.mcp_servers.assessments.improvement import (
    Observation,
    detect_weaknesses,
    target_score,
    trajectory_flag,
)

LEVELS = [{"score": s, "label": label} for s, label in
          ((1, "Beginning"), (2, "Developing"), (3, "Proficient"), (4, "Exemplary"))]
START = datetime(2026, 9, 1, tzinfo=UTC)


def _obs(day: int, score: int, key: str = "evidence", target: int | None = 3,
         criterion: str = "c-evidence", outcomes: tuple[str, ...] = ("o1",)) -> Observation:
    return Observation(
        submission_id=f"s{day}", person_id="p", version=1, status="draft",
        submitted_at=START + timedelta(days=day), criterion_id=criterion, key=key,
        score=score, target=target, outcome_nodes=outcomes,
    )


@pytest.mark.parametrize("levels,expected", [
    (LEVELS, 3),
    ([{"score": 1}, {"score": 2}, {"score": 3}, {"score": 4}], 3),
    ([{"score": 0}, {"score": 1}], 1),
    ([{"score": 5, "label": "proficient"}, {"score": 9}], 5),
    ([], None),
    (None, None),
    ([{"score": True}, {"score": "3"}], None),
])
def test_target_score(levels, expected) -> None:  # noqa: ANN001
    assert target_score(levels) == expected


@pytest.mark.parametrize("scores,status,expected", [
    ([2, 3], "draft", "ready_for_summative"),
    ([2, 3], "final", None),
    ([2, 2], "draft", "plateaued"),
    ([3, 3], "draft", "ready_for_summative"),
    ([3, 2], "draft", "regressed"),
    ([2, 4, 3], "draft", "regressed"),
    ([2], "draft", None),
    ([], "draft", None),
])
def test_trajectory_flag(scores, status, expected) -> None:  # noqa: ANN001
    assert trajectory_flag(scores, 3, status) == expected


def test_two_below_target_in_the_window_is_a_weakness() -> None:
    [weak] = detect_weaknesses([_obs(1, 2), _obs(2, 3), _obs(3, 2)], window=3)
    assert (weak["key"], weak["below_target_count"], weak["last_scores"]) == (
        "evidence", 2, [2, 3, 2])
    assert weak["outcome_nodes"] == ["o1"] and weak["window"] == 3


def test_one_below_target_is_not_a_weakness() -> None:
    assert detect_weaknesses([_obs(1, 2), _obs(2, 3), _obs(3, 4)], window=3) == []


def test_low_scores_older_than_the_window_do_not_count() -> None:
    history = [_obs(1, 1), _obs(2, 1), _obs(3, 3), _obs(4, 3), _obs(5, 2)]
    assert detect_weaknesses(history, window=3) == []
    assert detect_weaknesses(history, window=5)[0]["below_target_count"] == 3


def test_window_boundary_includes_the_nth_submission() -> None:
    history = [_obs(1, 2), _obs(2, 4), _obs(3, 2)]
    assert detect_weaknesses(history, window=2) == []
    assert len(detect_weaknesses(history, window=3)) == 1


def test_a_key_recurs_across_rubrics_and_reports_the_newest_criterion() -> None:
    history = [_obs(1, 2, criterion="essay1-evidence", outcomes=("o1",)),
               _obs(2, 1, criterion="essay2-evidence", outcomes=("o2", "o1"))]
    [weak] = detect_weaknesses(history, window=3)
    assert weak["criterion_id"] == "essay2-evidence"
    assert weak["outcome_nodes"] == ["o2", "o1"]


def test_criteria_without_a_target_never_count() -> None:
    assert detect_weaknesses([_obs(1, 0, target=None), _obs(2, 0, target=None)], 3) == []
