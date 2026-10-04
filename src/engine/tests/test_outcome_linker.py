from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.jobs.outcome_linker import (
    AttestationObs,
    CriterionAnchor,
    EvidenceObs,
    LinkableAction,
    ScoreObs,
    action_nodes,
    link_key,
    link_outcomes,
    visible_score,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=30)
WINDOW = timedelta(days=14)
STUDENT, OTHER = "s-1", "s-2"
NODE, NODE_B = "n-1", "n-2"
CRIT = "c-thesis"


def at(days: float) -> datetime:
    return T0 + timedelta(days=days)


def ev(eid: str, days: float, score: float | None = 0.5, *, person: str = STUDENT,
       node: str = NODE, criterion: str | None = None, cs_id: str | None = None,
       cs_score: float | None = None, visibility: str = "course") -> EvidenceObs:
    return EvidenceObs(eid, person, node, score, at(days), criterion, cs_id, cs_score,
                       visibility)


def att(aid: str, days: float, level: str, *, nodes: frozenset[str] = frozenset({NODE}),
        person: str = STUDENT) -> AttestationObs:
    return AttestationObs(aid, person, nodes, level, at(days))


def action(**kw) -> LinkableAction:
    return LinkableAction(id=kw.pop("id", "a-1"), subject=kw.pop("subject", STUDENT),
                          created_at=kw.pop("created_at", T0), **kw)


def run(actions, evidence=(), attestations=(), now=NOW, existing=None):
    return link_outcomes(actions, evidence, attestations, window=WINDOW, now=now,
                         existing=existing)


def test_next_node_evidence_links_with_before_and_after_scores():
    links = run([action(nodes=frozenset({NODE}))],
                [ev("old", -3, 0.4), ev("older", -5, 0.1), ev("next", 2, 0.7),
                 ev("later", 3, 0.9)])
    assert len(links) == 1
    assert links[0].evidence_id == "next"
    assert links[0].observed_at == at(2)
    assert links[0].delta == {"kind": "node_evidence", "node_id": NODE, "before": 0.4,
                              "after": 0.7, "change": 0.3}


def test_evidence_without_prior_has_null_before_and_change():
    [link] = run([action(nodes=frozenset({NODE}))], [ev("next", 1, 0.6)])
    assert link.delta["before"] is None and link.delta["change"] is None


def test_evidence_outside_window_other_student_or_node_is_ignored():
    links = run([action(nodes=frozenset({NODE}))],
                [ev("late", 14.01), ev("other", 1, person=OTHER), ev("b", 1, node=NODE_B),
                 ev("at-action", 0)])
    assert links == []


def test_window_end_is_inclusive_and_capped_by_now():
    assert [link.evidence_id for link in run([action(nodes=frozenset({NODE}))],
                                             [ev("edge", 14)])] == ["edge"]
    assert run([action(nodes=frozenset({NODE}))], [ev("future", 5)], now=at(4)) == []


def test_next_attestation_links_level_change_and_skips_own_target():
    links = run([action(nodes=frozenset({NODE}), own_attestation="own")],
                attestations=[att("own", 0.001, "proficient"), att("next", 4, "mastery"),
                              att("set", 5, "emerging", nodes=frozenset({NODE_B, NODE}))])
    assert [(link.attestation_id, link.delta) for link in links] == [
        ("next", {"kind": "node_attestation", "node_id": NODE, "before": "proficient",
                  "after": "mastery", "change": 1})]


def test_attestation_matches_by_node_set():
    [link] = run([action(nodes=frozenset({NODE}))],
                 attestations=[att("prior", -1, "mastery"),
                               att("set", 2, "emerging", nodes=frozenset({NODE_B, NODE}))])
    assert link.attestation_id == "set"
    assert link.delta["change"] == -2


def test_criterion_links_next_evidence_on_a_different_criterion_score():
    anchor = CriterionAnchor(CRIT, "thesis", 2, "cs-own")
    links = run([action(criteria=(anchor,))],
                [ev("own-ev", 1, criterion=CRIT, cs_id="cs-own", cs_score=2),
                 ev("rev", 3, criterion=CRIT, cs_id="cs-rev", cs_score=3),
                 ev("other-crit", 2, criterion="c-other", cs_id="cs-x", cs_score=1)])
    assert len(links) == 1
    assert links[0].evidence_id == "rev"
    assert links[0].delta == {"kind": "criterion", "criterion_id": CRIT, "criterion": "thesis",
                              "before": 2.0, "after": 3.0, "change": 1.0}


def test_one_action_can_link_each_kind_and_anchor_once():
    links = run([action(nodes=frozenset({NODE, NODE_B}),
                        criteria=(CriterionAnchor(CRIT, "thesis", 1, "cs-own"),))],
                [ev("n1", 1), ev("n2", 2, node=NODE_B),
                 ev("c", 3, node=NODE_B, criterion=CRIT, cs_id="cs-2", cs_score=2)],
                [att("a", 1, "proficient")])
    assert sorted((link.delta["kind"], link.evidence_id or link.attestation_id)
                  for link in links) == [("criterion", "c"), ("node_attestation", "a"),
                                         ("node_evidence", "n1"), ("node_evidence", "n2")]


def test_existing_links_are_not_rewritten_and_rerun_is_identical():
    actions = [action(nodes=frozenset({NODE}))]
    evidence = [ev("next", 2, 0.7)]
    first = run(actions, evidence)
    assert run(actions, evidence) == first
    assert run(actions, evidence, existing={link.key for link in first}) == []


def test_an_earlier_observation_arriving_later_does_not_relink_the_anchor():
    actions = [action(nodes=frozenset({NODE}))]
    first = run(actions, [ev("b", 5)])
    assert run(actions, [ev("a", 1), ev("b", 5)], existing={first[0].key}) == []


def test_ties_break_by_id():
    [link] = run([action(nodes=frozenset({NODE}))], [ev("z", 2), ev("m", 2)])
    assert link.evidence_id == "m"


def test_action_nodes_reads_node_id_and_node_ids_and_drops_non_uuids():
    a, b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    assert action_nodes({"node_id": a, "node_ids": [b, "x", 3]}) == frozenset({a, b})
    assert action_nodes({"node_ids": "nope"}) == frozenset()


def test_private_evidence_is_never_linked_nor_used_as_before():
    links = run([action(nodes=frozenset({NODE}))],
                [ev("prior", -3, 0.4), ev("private-prior", -1, 0.1, visibility="private"),
                 ev("practice", 1, 0.9, visibility="private"), ev("next", 2, 0.7,
                                                                  visibility="program")])
    assert [(link.evidence_id, link.delta["before"]) for link in links] == [("next", 0.4)]


def test_private_criterion_evidence_is_not_linked():
    anchor = CriterionAnchor(CRIT, "thesis", 2, "cs-own")
    assert run([action(criteria=(anchor,))],
               [ev("practice", 1, criterion=CRIT, cs_id="cs-2", cs_score=3,
                   visibility="private")]) == []


def test_evidence_defaults_to_private():
    assert EvidenceObs("e", STUDENT, NODE, 0.5, T0).visibility == "private"


def rescore(sid: str, days: float, score: int | None, *, person: str = STUDENT,
            criterion: str = CRIT) -> ScoreObs:
    return ScoreObs(sid, person, criterion, score, at(days), f"sub-{sid}")


def test_a_revision_scored_on_the_criterion_links_the_delta():
    anchor = CriterionAnchor(CRIT, "evidence", 2, "own-score")
    [link] = link_outcomes([action(criteria=(anchor,))], [], [], window=WINDOW, now=NOW,
                           scores=[rescore("own-score", 0, 2), rescore("v2", 1, 3),
                                   rescore("v3", 2, 4), rescore("x", 1, 1, person=OTHER),
                                   rescore("late", 20, 4)])
    assert link.evidence_id is None and link.observed_at == at(1)
    assert link.delta == {"kind": "criterion", "criterion_id": CRIT, "criterion": "evidence",
                          "before": 2.0, "after": 3.0, "change": 1.0,
                          "submission_id": "sub-v2"}


def test_criterion_evidence_earlier_than_a_rescore_wins():
    anchor = CriterionAnchor(CRIT, "evidence", 2, "own-score")
    [link] = link_outcomes([action(criteria=(anchor,))],
                           [ev("e", 1, 0.5, criterion=CRIT, cs_id="other", cs_score=4)], [],
                           window=WINDOW, now=NOW, scores=[rescore("v2", 2, 3)])
    assert link.evidence_id == "e" and link.delta["after"] == 4.0


def test_a_server_written_revision_link_counts_as_existing():
    server_row = {"criterion": "evidence", "criterion_id": CRIT, "before": 2, "after": 3,
                  "delta": 1}
    anchor = CriterionAnchor(CRIT, "evidence", 2, "own-score")
    links = link_outcomes([action(criteria=(anchor,))], [], [], window=WINDOW, now=NOW,
                          existing={link_key("a-1", server_row)},
                          scores=[rescore("v2", 1, 3)])
    assert links == []


def test_an_unseen_revision_score_leaves_the_anchor_open_for_a_later_seen_one():
    anchor = CriterionAnchor(CRIT, "evidence", 2, "own-score")
    unseen = link_outcomes([action(criteria=(anchor,))],
                           [ev("e", 0.5, criterion=CRIT, cs_id="v2", cs_score=None)], [],
                           window=WINDOW, now=NOW, scores=[rescore("v2", 1, None)])
    [link] = link_outcomes([action(criteria=(anchor,))], [], [], window=WINDOW, now=NOW,
                           scores=[rescore("v2", 1, None), rescore("v3", 2, 3)])
    assert unseen == []
    assert link.delta["after"] == 3.0 and link.delta["submission_id"] == "sub-v3"


def test_feedback_its_learner_never_saw_is_not_linked():
    anchor = CriterionAnchor(CRIT, "evidence", None, "own-score")
    assert link_outcomes([action(criteria=(anchor,))], [], [], window=WINDOW, now=NOW,
                         scores=[rescore("v2", 1, 3)]) == []


def test_visible_score_is_the_committed_final_else_the_released_ai_score():
    assert visible_score(4, True, 2, True) == 4
    assert visible_score(4, False, 2, True) == 2
    assert visible_score(None, True, 2, True) == 2
    assert visible_score(4, False, 2, False) is None
    assert visible_score(None, False, 2, False) is None
