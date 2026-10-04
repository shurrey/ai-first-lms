"""POST /api/assignments/{id}/alignment/decisions and POST /api/practice/{id}/attempts
against in-memory stores and recorded MCP calls."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import engine.agents.runner as runner_mod
from engine.api.practice import expected_answer
from engine.provenance import (
    ALIGNMENT_TOOL,
    AiActionRow,
    ProvenanceRecorder,
    ToolCallFacts,
)
from engine.tests.auth_fakes import CS101, ENG102
from engine.tests.formative_fakes import InMemoryFormativeStore, RecordingTools, new_id
from engine.tests.provenance_fakes import InMemoryProvenanceStore

APPLY = "assessments.apply_alignment"
ATTEMPT = "assessments.record_practice_attempt"
LEVELS = [{"score": 1, "label": "Beginning", "descriptor": "Missing."},
          {"score": 2, "label": "Developing", "descriptor": "Partial."},
          {"score": 3, "label": "Proficient", "descriptor": "Clear."}]


def _criterion(key: str, outcome: str) -> dict[str, Any]:
    return {"key": key, "description": f"{key} description", "levels": LEVELS,
            "outcome_nodes": [outcome]}


@pytest.fixture
def provenance() -> InMemoryProvenanceStore:
    return InMemoryProvenanceStore()


@pytest.fixture
def store() -> InMemoryFormativeStore:
    return InMemoryFormativeStore()


@pytest.fixture
def tools(monkeypatch) -> RecordingTools:
    recorder = RecordingTools()
    monkeypatch.setattr(runner_mod, "_call_mcp_json", recorder)
    return recorder


@pytest.fixture
def app(auth_app, store, provenance, tools):
    auth_app.state.formative_store = store
    auth_app.state.provenance = ProvenanceRecorder(provenance)
    return auth_app


# --- alignment decisions --------------------------------------------------------------------


OUTCOME = new_id()


async def _proposal(provenance: InMemoryProvenanceStore, assignment: str, course: str) -> str:
    action_id = new_id()
    await provenance.record_action(AiActionRow(
        id=action_id, agent="course_architect", action_type="generation",
        output={"tool": ALIGNMENT_TOOL, "assignment_node": assignment, "proposal": {
            "criteria": [_criterion(k, OUTCOME) for k in ("thesis", "evidence", "style")],
            "outcome_links": []}},
        course_node=course, target_type="nodes", target_id=assignment))
    return action_id


def _decisions(provenance: InMemoryProvenanceStore, action_id: str) -> list[tuple[str, Any]]:
    return [(d.decision, d.diff) for d in provenance.decided if d.ai_action_id == action_id]


async def test_faculty_accept_edit_and_reject_each_proposed_criterion(
        app, store, provenance, tools, authed_client, auth_world):
    assignment = store.add_assignment(CS101.course_id)
    action = await _proposal(provenance, assignment.id, CS101.course_id)
    tools.replies[APPLY] = {"rubric_id": assignment.rubric_id, "criterion_ids": ["c1", "c2"],
                            "created": 2, "updated": 0}
    edited = {**_criterion("evidence", OUTCOME), "description": "Cites two sources."}
    faculty = await authed_client("faculty")

    resp = await faculty.post(f"/api/assignments/{assignment.id}/alignment/decisions", json={
        "decisions": [{"key": "thesis", "decision": "accept"},
                      {"key": "evidence", "decision": "edit", "criterion": edited},
                      {"key": "style", "decision": "reject", "reason": "Not assessed here."}]})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["ai_action_id"], body["rubric_id"], body["criterion_ids"]) == (
        action, assignment.rubric_id, ["c1", "c2"])
    assert [d["decision"] for d in body["decisions"]] == ["accepted", "edited", "rejected"]
    assert tools.calls_to(APPLY) == [{
        "assignment_node": assignment.id, "requester_id": auth_world.people["faculty"].id,
        "criteria": [_criterion("thesis", OUTCOME), edited]}]
    assert _decisions(provenance, action) == [
        ("accepted", {"criterion_key": "thesis"}),
        ("edited", {"criterion_key": "evidence", "changed": True, "fields": {
            "description": {"before": "evidence description",
                            "after": "Cites two sources."}}}),
        ("rejected", {"criterion_key": "style"})]
    assert provenance.decided[-1].reason == "Not assessed here."


async def test_concurrent_decisions_on_one_proposal_apply_it_once(
        app, store, provenance, tools, authed_client, monkeypatch):
    assignment = store.add_assignment(CS101.course_id)
    action = await _proposal(provenance, assignment.id, CS101.course_id)
    tools.replies[APPLY] = {"rubric_id": assignment.rubric_id, "criterion_ids": ["c1"]}

    async def slow_tool(tool: str, args: dict[str, Any]) -> Any:
        await asyncio.sleep(0.02)
        return await tools(tool, args)

    monkeypatch.setattr(runner_mod, "_call_mcp_json", slow_tool)
    faculty = await authed_client("faculty")
    url = f"/api/assignments/{assignment.id}/alignment/decisions"
    body = {"ai_action_id": action, "decisions": [{"key": "thesis", "decision": "accept"}]}

    first, second = await asyncio.gather(faculty.post(url, json=body),
                                         faculty.post(url, json=body))

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    assert len(tools.calls_to(APPLY)) == 1
    assert len(_decisions(provenance, action)) == 1


async def test_rejecting_every_criterion_writes_nothing_but_the_decisions(
        app, store, provenance, tools, authed_client):
    assignment = store.add_assignment(CS101.course_id)
    action = await _proposal(provenance, assignment.id, CS101.course_id)
    faculty = await authed_client("faculty")

    resp = await faculty.post(f"/api/assignments/{assignment.id}/alignment/decisions", json={
        "ai_action_id": action,
        "decisions": [{"key": k, "decision": "reject"} for k in ("thesis", "evidence")]})

    assert resp.status_code == 201, resp.text
    assert resp.json()["rubric_id"] is None
    assert tools.calls_to(APPLY) == []
    assert [d for d, _ in _decisions(provenance, action)] == ["rejected", "rejected"]


async def test_alignment_decisions_are_for_faculty_of_the_assignments_course(
        app, store, provenance, tools, authed_client):
    cs = store.add_assignment(CS101.course_id)
    eng = store.add_assignment(ENG102.course_id)
    await _proposal(provenance, cs.id, CS101.course_id)
    await _proposal(provenance, eng.id, ENG102.course_id)
    body = {"decisions": [{"key": "thesis", "decision": "accept"}]}

    for actor, assignment in (("student", cs), ("faculty", eng), ("admin", cs),
                              ("program_lead", cs)):
        client = await authed_client(actor)
        resp = await client.post(f"/api/assignments/{assignment.id}/alignment/decisions",
                                 json=body)
        assert resp.status_code == 403, actor
    assert tools.calls_to(APPLY) == [] and provenance.decided == []


async def test_alignment_decision_refusals(app, store, provenance, tools, authed_client):
    assignment = store.add_assignment(CS101.course_id)
    other = store.add_assignment(CS101.course_id)
    action = await _proposal(provenance, assignment.id, CS101.course_id)
    elsewhere = await _proposal(provenance, other.id, CS101.course_id)
    faculty = await authed_client("faculty")
    path = f"/api/assignments/{assignment.id}/alignment/decisions"
    accept = [{"key": "thesis", "decision": "accept"}]

    async def status(url: str, body: dict[str, Any]) -> int:
        return (await faculty.post(url, json=body)).status_code

    assert await status(f"/api/assignments/{new_id()}/alignment/decisions",
                        {"decisions": accept}) == 404
    bare = store.add_assignment(CS101.course_id)
    assert await status(f"/api/assignments/{bare.id}/alignment/decisions",
                        {"decisions": accept}) == 404
    assert await status(path, {"ai_action_id": elsewhere, "decisions": accept}) == 404
    assert await status(path, {"decisions": [{"key": "voice", "decision": "accept"}]}) == 422
    assert await status(path, {"decisions": accept * 2}) == 422
    assert await status(path, {"decisions": [{"key": "thesis", "decision": "edit"}]}) == 422
    assert await status(path, {"decisions": []}) == 422
    for code, expected in (("conflict", 409), ("validation_error", 422), (None, 502)):
        tools.replies[APPLY] = {"error": "refused", "code": code}
        assert await status(path, {"ai_action_id": action, "decisions": accept}) == expected
    assert provenance.decided == []


async def test_an_edit_may_not_rename_the_proposed_criterion(
        app, store, provenance, tools, authed_client):
    assignment = store.add_assignment(CS101.course_id)
    await _proposal(provenance, assignment.id, CS101.course_id)
    faculty = await authed_client("faculty")

    resp = await faculty.post(f"/api/assignments/{assignment.id}/alignment/decisions", json={
        "decisions": [{"key": "thesis", "decision": "edit",
                       "criterion": _criterion("evidence", OUTCOME)}]})

    assert resp.status_code == 422
    assert tools.calls_to(APPLY) == [] and provenance.decided == []


async def test_a_proposed_criterion_is_decided_only_once(
        app, store, provenance, tools, authed_client):
    assignment = store.add_assignment(CS101.course_id)
    action = await _proposal(provenance, assignment.id, CS101.course_id)
    tools.replies[APPLY] = {"rubric_id": assignment.rubric_id, "criterion_ids": ["c1"]}
    faculty = await authed_client("faculty")
    path = f"/api/assignments/{assignment.id}/alignment/decisions"

    first = await faculty.post(path, json={"decisions": [{"key": "thesis", "decision": "accept"}]})
    again = await faculty.post(path, json={"ai_action_id": action, "decisions": [
        {"key": "evidence", "decision": "reject"}, {"key": "thesis", "decision": "reject"}]})
    rest = await faculty.post(path, json={"decisions": [
        {"key": "evidence", "decision": "reject"}]})

    assert (first.status_code, again.status_code, rest.status_code) == (201, 409, 201)
    assert len(tools.calls_to(APPLY)) == 1
    assert _decisions(provenance, action) == [("accepted", {"criterion_key": "thesis"}),
                                              ("rejected", {"criterion_key": "evidence"})]


async def test_a_validated_alignment_proposal_is_recorded_as_a_generation(provenance):
    recorder = ProvenanceRecorder(provenance)
    assignment, course, syllabus = new_id(), CS101.course_id, new_id()

    def facts(result: dict[str, Any]) -> ToolCallFacts:
        return ToolCallFacts(agent="course_architect", tool=ALIGNMENT_TOOL, call_key=new_id(),
                             requester_id=new_id(), args={"assignment_node": assignment},
                             proposed={"assignment_node": assignment}, result=result)

    await recorder.tool_succeeded(facts({"assignment_node": assignment, "proposal": None}))
    await recorder.tool_succeeded(facts({
        "assignment_node": assignment, "course_id": course,
        "syllabus": {"content_id": syllabus}, "proposal": {"criteria": []}}))

    [row] = provenance.actions
    assert (row.action_type, row.target_type, row.target_id, row.course_node) == (
        "generation", "nodes", assignment, course)
    assert row.output == {"tool": ALIGNMENT_TOOL, "assignment_node": assignment,
                          "proposal": {"criteria": []}}
    assert {(s["type"], s["id"]) for s in row.sources} == {
        ("node", assignment), ("content_item", syllabus)}


# --- practice attempts ----------------------------------------------------------------------


async def _practice_set(provenance: InMemoryProvenanceStore, person: str) -> str:
    action_id = new_id()
    await provenance.record_action(AiActionRow(
        id=action_id, agent="content_generator", action_type="practice_item",
        output={"practice_set_id": action_id}, subject_person=person,
        course_node=CS101.course_id, target_type="question_banks", target_id=new_id()))
    return action_id


async def test_a_learner_answers_their_practice_set_and_gets_it_marked(
        app, provenance, tools, authed_client, auth_world):
    emma = auth_world.people["student"].id
    practice = await _practice_set(provenance, emma)
    q1, q2 = new_id(), new_id()
    tools.replies[ATTEMPT] = {
        "practice_set_id": practice, "evidence_ids": ["ev-1", "ev-2"], "score": 1.0,
        "items": [
            {"question_id": q1, "correct": True,
             "answer_key": {"correct": ["B", "b)"], "explanation": "B cites the study."}},
            {"question_id": q2, "correct": None,
             "answer_key": {"model_points": ["Names a source", "Links it to the claim"]}}]}

    resp = await (await authed_client("student")).post(
        f"/api/practice/{practice}/attempts",
        json={"answers": [{"question_id": q1, "answer": "B"},
                          {"question_id": q2, "answer": "Because the survey says so."}]})

    assert resp.status_code == 201, resp.text
    assert resp.json() == {
        "practice_set_id": practice, "attempt_id": "ev-1", "correct": 1, "total": 2,
        "results": [
            {"question_id": q1, "correct": True, "expected": "B or b)",
             "feedback": "B cites the study."},
            {"question_id": q2, "correct": None,
             "expected": "Names a source; Links it to the claim", "feedback": None}]}
    assert tools.calls_to(ATTEMPT) == [{
        "person_id": emma, "practice_set_id": practice,
        "answers": [{"question_id": q1, "answer": "B"},
                    {"question_id": q2, "answer": "Because the survey says so."}]}]


async def test_only_the_sets_learner_may_attempt_it(app, provenance, tools, authed_client,
                                                    auth_world):
    practice = await _practice_set(provenance, auth_world.people["student"].id)
    answers = {"answers": [{"question_id": new_id(), "answer": "B"}]}
    noah = await authed_client("student", person="noah")

    assert (await noah.post(f"/api/practice/{practice}/attempts",
                            json=answers)).status_code == 404
    for actor in ("faculty", "advisor", "admin"):
        client = await authed_client(actor)
        assert (await client.post(f"/api/practice/{practice}/attempts",
                                  json=answers)).status_code == 403, actor
    assert tools.calls_to(ATTEMPT) == []


async def test_practice_attempt_refusals(app, provenance, tools, authed_client, auth_world):
    emma = auth_world.people["student"].id
    practice = await _practice_set(provenance, emma)
    not_practice = new_id()
    await provenance.record_action(AiActionRow(id=not_practice, agent="tutor",
                                          action_type="recommendation", output={},
                                          subject_person=emma))
    student = await authed_client("student")
    q = new_id()
    one = {"answers": [{"question_id": q, "answer": "B"}]}

    async def status(set_id: str, body: dict[str, Any]) -> int:
        return (await student.post(f"/api/practice/{set_id}/attempts", json=body)).status_code

    assert await status(new_id(), one) == 404
    assert await status(not_practice, one) == 404
    assert await status(practice, {"answers": []}) == 422
    assert await status(practice, {"answers": one["answers"] * 2}) == 422
    assert await status(practice, {"answers": [{"question_id": q, "answer": "x" * 5001}]}) == 422
    assert await status(practice, {"answers": [{"question_id": q, "answer": 2}]}) == 422
    assert tools.calls_to(ATTEMPT) == []
    for code, expected in (("not_found", 404), ("validation_error", 422),
                           ("forbidden", 403), (None, 502)):
        tools.replies[ATTEMPT] = {"error": "refused", "code": code}
        assert await status(practice, one) == expected
    tools.replies[ATTEMPT] = {"evidence_ids": []}
    assert await status(practice, one) == 502


@pytest.mark.parametrize("key,expected", [
    ({"correct": "B"}, "B"),
    ({"correct": 3}, "3"),
    ({"correct": ["yes", "y"]}, "yes or y"),
    ({"model_answer": "A thesis that takes a side."}, "A thesis that takes a side."),
    ({"model_points": ["one", "", "two"]}, "one; two"),
    ({"explanation": "only"}, None),
    ({"correct": True}, None),
    ("B", None),
])
def test_expected_answer_reads_the_stored_answer_key(key, expected):
    assert expected_answer(key) == expected
