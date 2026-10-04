"""Pure parts of the formative loop: verbatim spans, policy defaults, status and view shaping."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from engine.formative.policy import release_mode, show_scores_on_drafts, weakness_window
from engine.formative.spans import MAX_QUOTE_CHARS, check_spans
from engine.formative.store import CriterionRow
from engine.formative.views import (
    awaiting,
    chain_of,
    changed_fields,
    criterion_feedback,
    feedback_status,
    improvement,
    is_rejected,
    next_step,
    version_scores,
)
from engine.tests.formative_fakes import T0, InMemoryFormativeStore, new_id

BODY = "The survey found most teens feel pressure. Schools should act."


# --- spans --------------------------------------------------------------------------------


def test_spans_keep_verbatim_quotes_and_correct_their_offsets():
    check = check_spans(BODY, [{"quote": "Schools should act."},
                               {"quote": "The survey", "start": 0, "end": 10},
                               {"quote": "most teens", "start": 0, "end": 10}])

    assert check.kept == [
        {"quote": "Schools should act.", "start": 43, "end": 62},
        {"quote": "The survey", "start": 0, "end": 10},
        {"quote": "most teens", "start": 17, "end": 27},
    ]
    assert check.dropped == []
    assert all(BODY[s["start"]:s["end"]] == s["quote"] for s in check.kept)


def test_spans_drop_paraphrases_and_malformed_entries():
    check = check_spans(BODY, [{"quote": "the survey found most teens"}, {"quote": "  "},
                               "not a span", {"start": 0}])

    assert check.kept == []
    assert check.dropped == [
        {"quote": "the survey found most teens", "reason": "not_verbatim"},
        {"quote": "  ", "reason": "missing_quote"},
        {"quote": None, "reason": "missing_quote"},
        {"quote": None, "reason": "missing_quote"},
    ]


def test_spans_drop_verbatim_quotes_longer_than_the_cap():
    body = "x" * (MAX_QUOTE_CHARS + 50)

    check = check_spans(body, [{"quote": body}, {"quote": "x" * MAX_QUOTE_CHARS}])

    assert check.kept == [{"quote": "x" * MAX_QUOTE_CHARS, "start": 0, "end": MAX_QUOTE_CHARS}]
    assert check.dropped == [{"quote": "x" * MAX_QUOTE_CHARS, "reason": "too_long"}]


def test_spans_tolerate_a_missing_list():
    assert check_spans(BODY, None).kept == []


# --- policy -------------------------------------------------------------------------------


async def test_release_mode_defaults_to_instructor_release():
    store = InMemoryFormativeStore()

    assert await release_mode(store, "c1") == "instructor_release"
    assert await release_mode(store, None) == "instructor_release"


async def test_a_course_setting_overrides_release_mode_when_valid():
    store = InMemoryFormativeStore(settings={("c1", "feedback.release_mode"): "auto",
                                             ("c2", "feedback.release_mode"): "sometimes"})

    assert await release_mode(store, "c1") == "auto"
    assert await release_mode(store, "c2") == "instructor_release"


@pytest.mark.parametrize(("value", "expected"), [(5, 5), (1, 3), (11, 3), (True, 3), ("4", 3)])
async def test_weakness_window_accepts_only_integers_from_2_to_10(value, expected):
    store = InMemoryFormativeStore(settings={("c1", "feedback.weakness_window"): value})

    assert await weakness_window(store, "c1") == expected


async def test_show_scores_on_drafts_defaults_to_true():
    store = InMemoryFormativeStore(settings={("c2", "feedback.show_scores_on_drafts"): False})

    assert await show_scores_on_drafts(store, "c1") is True
    assert await show_scores_on_drafts(store, "c2") is False


# --- status and per-criterion decisions -------------------------------------------------


def _setup():
    store = InMemoryFormativeStore()
    assignment = store.add_assignment("c1")
    sub = store.add_submission(assignment, "p1")
    return store, assignment, sub


async def _state(store, sub):
    criteria = (await store.criteria([sub.id]))[sub.id]
    actions = [c.ai_action_id for c in criteria if c.ai_action_id]
    return criteria, await store.action_outputs(actions), await store.decisions(actions)


async def test_status_moves_from_pending_to_awaiting_to_released():
    store, _, sub = _setup()
    criteria, _, decisions = await _state(store, sub)
    assert feedback_status(sub, criteria, decisions) == "pending"

    action = store.score(sub, "thesis", 3)
    store.score(sub, "evidence", 2, action=action)
    criteria, _, decisions = await _state(store, sub)
    assert feedback_status(sub, criteria, decisions) == "awaiting_release"

    store.scores[(sub.id, criteria[0].criterion_id)]["released_at"] = T0
    criteria, _, decisions = await _state(store, sub)
    assert feedback_status(sub, criteria, decisions) == "released"


async def test_status_is_failed_when_saved_feedback_was_never_released():
    store = InMemoryFormativeStore()
    assignment = store.add_assignment("c1")
    sub = store.add_submission(assignment, "emma")
    store.score(sub, "evidence", 2)
    criteria = (await store.criteria([sub.id]))[sub.id]

    assert feedback_status(sub, criteria, {}, failed=True) == "failed"
    store.score(sub, "thesis", 3, released=True)
    criteria = (await store.criteria([sub.id]))[sub.id]
    assert feedback_status(sub, criteria, {}, failed=True) == "released"


async def test_status_is_none_for_finals_and_suppressed_when_every_criterion_is_rejected():
    store, assignment, sub = _setup()
    final = store.add_submission(assignment, "p1", status="final", parent=sub)
    action = store.score(sub, "thesis", 3)
    store.score(sub, "evidence", 2, action=action)
    for key in ("thesis", "evidence"):
        store.decide(action, store.criterion(assignment, key).criterion_id, "rejected")

    criteria, _, decisions = await _state(store, sub)
    assert feedback_status(sub, criteria, decisions) == "suppressed"
    assert feedback_status(final, [], {}) == "none"


async def test_a_decision_applies_only_to_the_criterion_its_diff_names():
    store, assignment, sub = _setup()
    action = store.score(sub, "thesis", 3)
    store.score(sub, "evidence", 2, action=action)
    store.decide(action, store.criterion(assignment, "thesis").criterion_id, "rejected")

    criteria, _, decisions = await _state(store, sub)
    by_key = {c.key: c for c in criteria}
    assert is_rejected(by_key["thesis"], decisions)
    assert not is_rejected(by_key["evidence"], decisions)
    assert [c.key for c in awaiting(criteria, decisions)] == ["evidence"]
    assert feedback_status(sub, criteria, decisions) == "awaiting_release"


async def test_next_step_prefers_the_latest_instructor_edit():
    store, assignment, sub = _setup()
    action = store.score(sub, "thesis", 3, next_step="Sharpen the claim.")
    criteria, outputs, decisions = await _state(store, sub)
    thesis = criteria[0] if criteria[0].key == "thesis" else criteria[1]
    assert next_step(thesis, outputs[action], decisions) == "Sharpen the claim."

    store.decide(action, thesis.criterion_id, "edited",
                 {"fields": {"next_step": {"before": "Sharpen the claim.",
                                           "after": "State the claim first."}}})
    _, outputs, decisions = await _state(store, sub)
    assert next_step(thesis, outputs[action], decisions) == "State the claim first."


def test_next_step_reads_a_top_level_output_too():
    criterion = CriterionRow("s", "c", "thesis", "d")
    assert next_step(criterion, {"next_step": "Do this."}, {}) == "Do this."
    assert next_step(criterion, {}, {}) is None


async def test_criterion_feedback_hides_the_score_and_its_label_when_asked():
    store, _, sub = _setup()
    action = store.score(sub, "thesis", 2)
    criteria, outputs, decisions = await _state(store, sub)
    thesis = next(c for c in criteria if c.key == "thesis")

    shown = criterion_feedback(thesis, outputs[action], decisions, hide_score=False)
    hidden = criterion_feedback(thesis, outputs[action], decisions, hide_score=True)

    assert (shown["ai_score"], shown["level_label"]) == (2, "Developing")
    assert (hidden["ai_score"], hidden["level_label"]) == (None, None)
    assert hidden["ai_rationale"] == "thesis rationale" and hidden["next_step"] == "Next."


async def test_changed_fields_keeps_only_real_changes():
    store, _, sub = _setup()
    action = store.score(sub, "thesis", 2, next_step="Same.")
    criteria, outputs, decisions = await _state(store, sub)
    thesis = next(c for c in criteria if c.key == "thesis")

    changed = changed_fields(thesis, outputs[action], decisions,
                             {"ai_score": 2, "ai_rationale": "New why.", "next_step": "Same."})

    assert changed == {"ai_rationale": "New why."}


# --- chains and deltas --------------------------------------------------------------------


def test_chain_of_follows_parents_and_the_latest_child():
    store, assignment, v1 = _setup()
    v2 = store.add_submission(assignment, "p1", parent=v1)
    v2b = store.add_submission(assignment, "p1", parent=v1, at=v2.submitted_at - timedelta(1))
    v3 = store.add_submission(assignment, "p1", parent=v2)
    rows = [v1, v2, v2b, v3]

    assert [r.id for r in chain_of(rows, v1.id)] == [v1.id, v2.id, v3.id]
    assert [r.id for r in chain_of(rows, v2b.id)] == [v1.id, v2b.id]
    assert chain_of(rows, new_id()) == []


def test_version_scores_compute_deltas_between_visible_scores():
    store, assignment, v1 = _setup()
    v2 = store.add_submission(assignment, "p1", parent=v1)
    evidence = store.criterion(assignment, "evidence")
    thesis = store.criterion(assignment, "thesis")
    criteria = {v1.id: [replace(evidence, ai_score=2), replace(thesis, ai_score=3)],
                v2.id: [replace(evidence, ai_score=3), replace(thesis, ai_score=None)]}

    def shown(c):
        return c.ai_score if c.key == "evidence" else (c.ai_score or False)

    out = version_scores([v1, v2], criteria, shown)

    assert out[0] == [{"criterion_id": evidence.criterion_id, "criterion_key": "evidence",
                       "score": 2, "delta": None},
                      {"criterion_id": thesis.criterion_id, "criterion_key": "thesis",
                       "score": 3, "delta": None}]
    assert out[1] == [{"criterion_id": evidence.criterion_id, "criterion_key": "evidence",
                       "score": 3, "delta": 1}]


# --- improvement --------------------------------------------------------------------------

RAW = {
    "course_id": "c1",
    "criteria": [{"criterion_id": "k1", "key": "evidence", "target_score": 3}],
    "students": [
        {"student_id": "s1", "display_name": "Emma", "trajectories": [
            {"criterion_id": "k1", "points": [
                {"submission_id": "a", "version": 1, "status": "draft", "score": 2,
                 "at": "2026-09-20T09:00:00+00:00"},
                {"submission_id": "b", "version": 2, "status": "draft", "score": 3,
                 "at": "2026-09-21T09:00:00+00:00"}],
             "delta": 1, "flag": "ready_for_summative"}]},
        {"student_id": "s2", "display_name": "Noah", "trajectories": [
            {"criterion_id": "k1", "points": [], "delta": None, "flag": "plateaued"}]},
    ],
}
INFO = {"k1": CriterionRow("", "k1", "evidence", "Supports claims with evidence")}


def test_improvement_full_view_maps_points_and_computes_the_aggregate():
    body = improvement(RAW, "c1", view="full", descriptions=INFO, names={},
                       students_allowed=None)

    assert body["criteria"] == [{"criterion_id": "k1", "criterion_key": "evidence",
                                 "description": "Supports claims with evidence",
                                 "target_score": 3}]
    emma = body["students"][0]
    assert emma["display_name"] == "Emma"
    assert emma["trajectories"][0]["points"][1] == {
        "submission_id": "b", "version": 2, "status": "draft", "score": 3,
        "submitted_at": "2026-09-21T09:00:00+00:00"}
    assert emma["trajectories"][0]["latest_delta"] == 1
    assert body["aggregate"] == [{"criterion_id": "k1", "n_students": 2, "mean_delta": 1.0,
                                  "flag_counts": {"ready_for_summative": 1, "plateaued": 1}}]


def test_improvement_summary_keeps_allowed_students_without_points():
    body = improvement(RAW, "c1", view="summary", descriptions=INFO, names={},
                       students_allowed=frozenset({"s2"}))

    assert [s["student_id"] for s in body["students"]] == ["s2"]
    assert body["students"][0]["trajectories"][0]["points"] == []


def test_improvement_aggregate_and_self_views():
    raw = {**RAW, "aggregate": [{"criterion_id": "k1", "n_students": 9, "mean_delta": 0.5,
                                 "flag_counts": {"regressed": 2}}]}

    aggregate = improvement(raw, "c1", view="aggregate", descriptions=INFO, names={},
                            students_allowed=None)
    own = improvement(RAW, "c1", view="self", descriptions=INFO, names={"s1": "Emma S."},
                      students_allowed=frozenset({"s1"}))

    assert aggregate["students"] == []
    assert aggregate["aggregate"] == [{"criterion_id": "k1", "n_students": 9,
                                       "mean_delta": 0.5, "flag_counts": {"regressed": 2}}]
    assert "aggregate" not in own
    assert [s["display_name"] for s in own["students"]] == ["Emma S."]
