"""Provenance write points (spec.md §6.4) through the gateway, runner, REST and analyst."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import engine.agents.runner as runner_mod
import engine.analyst as analyst
from engine.agents.runner import ClaudeAgentRunner
from engine.app import create_app
from engine.guardrails.approval import ApprovalDecision, ApprovalGate
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.provenance import (
    AiActionRow,
    ProvenanceRecorder,
    ProvenanceTrail,
    grade_diff,
    prompt_sha256,
    stable_id,
    text_edit_stats,
)
from engine.tests.auth_fakes import CS101, AuthWorld, auth_context, build_auth_world
from engine.tests.object_fakes import InMemoryObjectDirectory
from engine.tests.provenance_fakes import InMemoryProvenanceStore
from engine.turn_repository import turn_db_id

SUB = "11111111-1111-4111-8111-111111111111"
RUBRIC = "22222222-2222-4222-8222-222222222222"
G1 = "33333333-3333-4333-8333-333333333331"
G2 = "33333333-3333-4333-8333-333333333332"
CONCEPT = "44444444-4444-4444-8444-444444444444"
MICRO = "55555555-5555-4555-8555-555555555555"
PENDING = "66666666-6666-4666-8666-666666666666"
ATTESTATION = "77777777-7777-4777-8777-777777777777"
SESSION = "88888888-8888-4888-8888-888888888888"
BANK = "99999999-9999-4999-8999-999999999999"
QUESTION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class Mcp:
    """Every MCP server; draft_grade hands out G1 then G2."""

    def __init__(self, student_id: str) -> None:
        self.student_id = student_id
        self.grades = [G1, G2]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, dict(args)))
        replies: dict[str, Any] = {
            "assessments.get_submission": {"id": args.get("submission_id"),
                                           "person_id": self.student_id,
                                           "assignment_node": "a1"},
            "assessments.get_rubric": {"id": RUBRIC, "title": "Essay", "criteria": []},
            "assessments.commit_grade": {"committed": True,
                                         "committed_at": "2026-10-02T12:00:00Z"},
            "attestations.attest": {"attestation_id": ATTESTATION, "level": "mastery",
                                    "created": True,
                                    "credentials_pending": [{"microcredential_id": MICRO,
                                                             "title": "Recursion"}]},
            "assessments.approve_credential": {"approved": True, "credential_id": "c1"},
            "content.save_skill": {"id": QUESTION, "created": True},
            "assessments.create_question": {"question_id": QUESTION},
            "roster.get": {"id": args.get("person_id"), "display_name": "Emma Smith"},
            "graph.neighbors": {"nodes": [{"id": CS101.course_id, "kind": "course"}]},
        }
        if tool == "assessments.draft_grade":
            return json.dumps({"grade_id": self.grades.pop(0)})
        return json.dumps(replies.get(tool, {"updated": True}))

    def calls_to(self, tool: str) -> list[dict[str, Any]]:
        return [a for t, a in self.calls if t == tool]


class Events:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class Rig:
    def __init__(self, world: AuthWorld) -> None:
        self.world = world
        self.store = InMemoryProvenanceStore()
        self.store.pending[(world.people["student"].id, MICRO)] = PENDING
        world.directory.pending[PENDING] = CS101.course_id
        self.mcp = Mcp(world.people["student"].id)
        self.gate = ApprovalGate()
        self.events = Events()
        self.gateway = ToolGateway(
            self.mcp, directory=world.directory,
            objects=InMemoryObjectDirectory(submissions={SUB: CS101.course_id},
                                            banks={BANK: CS101.course_id}),
            approvals=self.gate, approval_timeout=5.0,
            provenance=ProvenanceRecorder(self.store),
        )
        self.trail = ProvenanceTrail(model="claude-test", prompt_sha256="ab" * 32)

    def ctx(self, person: str = "faculty", role: str | None = None) -> GatewayContext:
        return GatewayContext(auth=auth_context(self.world, person, role), session_id=SESSION,
                              turn_id="turn-1", step_id="s1", course_id=CS101.course_id,
                              emit=self.events, provenance=self.trail)

    async def call(self, tool: str, args: dict[str, Any], *, agent: str = "grading_assistant",
                   person: str = "faculty", call_id: str = "") -> Any:
        return await self.gateway.invoke(self.ctx(person), agent, tool, args,
                                         call_id=call_id or tool)

    async def gated(self, tool: str, args: dict[str, Any], decision: str, *,
                    agent: str = "grading_assistant", call_id: str = "",
                    edited: dict[str, Any] | None = None) -> Any:
        task = asyncio.create_task(self.call(tool, args, agent=agent, call_id=call_id))
        for _ in range(100):
            requests = [e for e in self.events.events if e["event"] == "approval_request"]
            pending = [r for r in requests
                       if self.gate.get_pending(r["payload"]["approval_id"]) is not None]
            if pending:
                break
            await asyncio.sleep(0)
        approval_id = pending[-1]["payload"]["approval_id"]
        request = self.gate.get_pending(approval_id)
        assert request is not None
        approver = auth_context(self.world, "faculty")
        arguments = edited if edited is not None else request.tool_arguments
        if decision != "reject":
            arguments = await self.gateway.authorize_approver(request, approver, arguments)
        self.gate.resolve(ApprovalDecision(approval_id, decision, edited),  # type: ignore[arg-type]
                          approver=approver, tool_arguments=arguments)
        return await task


def _draft(thesis: int, feedback: str = "Clear thesis.") -> dict[str, Any]:
    return {"submission_id": SUB, "rubric_id": RUBRIC,
            "scores": {"thesis": thesis, "evidence": 3},
            "feedback": {"thesis": feedback, "evidence": "Good sources."},
            "holistic_md": "Solid essay.", "graded_by": "anyone"}


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


@pytest.fixture
def rig(world: AuthWorld) -> Rig:
    return Rig(world)


# --- diffs -------------------------------------------------------------------------------


def test_grade_diff_reports_only_the_changed_criterion():
    diff = grade_diff(_draft(2), _draft(3, "Clear, arguable thesis."))
    assert diff["criteria"] == {"thesis": {"before": 2, "after": 3, "delta": 1}}
    assert set(diff["feedback"]) == {"thesis"}
    assert diff["feedback"]["thesis"]["chars_before"] == len("Clear thesis.")
    assert diff["holistic_md"] is None
    assert diff["changed"] is True


def test_grade_diff_reads_scores_nested_under_score():
    diff = grade_diff({"scores": {"c1": {"score": 1}}}, {"scores": {"c1": {"score": 4}}})
    assert diff["criteria"]["c1"]["delta"] == 3


def test_identical_grades_have_no_changes():
    assert grade_diff(_draft(2), _draft(2))["changed"] is False


def test_text_edit_stats():
    stats = text_edit_stats("abc", "abd")
    assert stats["edit_chars"] == 1
    assert 0 < stats["similarity"] < 1
    assert text_edit_stats("same", "same")["edit_chars"] == 0


# --- grading -----------------------------------------------------------------------------


async def test_draft_grade_records_a_grade_draft_with_its_sources(rig, world):
    await rig.call("assessments.get_rubric", {"rubric_id": RUBRIC}, call_id="tu0")
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")

    [action] = rig.store.of_type("grade_draft")
    assert (action.target_type, action.target_id) == ("grades", G1)
    assert action.subject_person == world.people["student"].id
    assert action.course_node == CS101.course_id
    assert action.session_id == SESSION and action.turn_id == "turn-1"
    assert action.output["scores"] == {"thesis": 2, "evidence": 3}
    assert "graded_by" not in action.output
    assert {(s["type"], s["id"]) for s in action.sources} == {
        ("submission", SUB), ("rubric", RUBRIC)}
    assert action.policies == []
    assert (action.model, action.prompt_sha256) == ("claude-test", "ab" * 32)


def test_trail_keeps_a_submission_only_for_actions_about_its_owner():
    other_sub, emma, noah = (str(uuid.uuid4()) for _ in range(3))
    trail = ProvenanceTrail()
    trail.observe("assessments.get_submission", {"submission_id": SUB},
                  {"id": SUB, "person_id": emma})
    trail.observe("assessments.get_submission", {"submission_id": other_sub},
                  {"id": other_sub, "person_id": noah})
    trail.observe("assessments.get_rubric", {"rubric_id": RUBRIC}, {"id": RUBRIC})

    def ids(subject: str | None) -> set[str]:
        return {s["id"] for s in trail.sources([], subject)}

    assert ids(emma) == {SUB, RUBRIC}
    assert ids(noah) == {other_sub, RUBRIC}
    assert ids(None) == {RUBRIC}


async def test_a_draft_does_not_list_another_learners_submission(rig, world):
    other_sub = str(uuid.uuid4())
    rig.trail.observe("assessments.get_submission", {"submission_id": other_sub},
                      {"id": other_sub, "person_id": world.people["noah"].id})
    await rig.call("assessments.get_submission", {"submission_id": SUB}, call_id="tu0")
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")

    [action] = rig.store.of_type("grade_draft")
    assert {s["id"] for s in action.sources} == {SUB, RUBRIC}


async def test_instructor_change_to_one_criterion_shows_in_the_diff(rig, world):
    """§6.6: the AI drafts thesis=2; the instructor has it redrafted at 3 and commits."""
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")
    await rig.call("assessments.draft_grade", _draft(3), call_id="tu2")
    result = await rig.gated("assessments.commit_grade", {"grade_id": G2}, "approve",
                             call_id="tu3")
    assert result.success

    first, second = rig.store.of_type("grade_draft")
    [edited] = rig.store.decisions_on(first.id)
    [accepted] = rig.store.decisions_on(second.id)
    assert edited.decision == "edited"
    assert edited.diff is not None
    assert edited.diff["criteria"] == {"thesis": {"before": 2, "after": 3, "delta": 1}}
    assert edited.decided_by == world.people["faculty"].id
    assert accepted.decision == "accepted"
    assert accepted.diff is not None and accepted.diff["changed"] is False


async def test_rejected_commit_is_recorded_as_rejected(rig):
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")
    result = await rig.gated("assessments.commit_grade", {"grade_id": G1}, "reject",
                             call_id="tu2")
    assert result.outcome == "gated"

    [draft] = rig.store.of_type("grade_draft")
    assert [d.decision for d in rig.store.decisions_on(draft.id)] == ["rejected"]


async def test_a_rejected_draft_stays_rejected_after_a_redraft_is_committed(rig):
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")
    await rig.gated("assessments.commit_grade", {"grade_id": G1}, "reject", call_id="tu2")
    await rig.call("assessments.draft_grade", _draft(3), call_id="tu3")
    result = await rig.gated("assessments.commit_grade", {"grade_id": G2}, "approve",
                             call_id="tu4")
    assert result.success

    first, second = rig.store.of_type("grade_draft")
    assert [d.decision for d in rig.store.decisions_on(first.id)] == ["rejected"]
    assert [d.decision for d in rig.store.decisions_on(second.id)] == ["accepted"]


async def test_the_same_tool_call_writes_once(rig):
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")
    rig.mcp.grades.insert(0, G1)
    await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")
    assert len(rig.store.of_type("grade_draft")) == 1


async def test_a_failed_store_write_does_not_fail_the_tool_call(rig):
    rig.store.fail = True
    result = await rig.call("assessments.draft_grade", _draft(2), call_id="tu1")
    assert result.success
    assert rig.store.actions == []


async def test_denied_calls_write_no_action(rig):
    result = await rig.call("assessments.draft_grade", _draft(2), person="student",
                            call_id="tu1")
    assert not result.success
    assert rig.store.actions == []


async def test_gateway_collects_the_ids_of_actions_it_wrote(rig):
    ids: list[str] = []
    ctx = replace(rig.ctx(), ai_action_ids=ids)
    await rig.gateway.invoke(ctx, "grading_assistant", "assessments.get_rubric",
                             {"rubric_id": RUBRIC}, call_id="tu0")
    await rig.gateway.invoke(ctx, "grading_assistant", "assessments.draft_grade", _draft(2),
                             call_id="tu1")
    rig.mcp.grades.insert(0, G1)
    await rig.gateway.invoke(ctx, "grading_assistant", "assessments.draft_grade", _draft(2),
                             call_id="tu1")

    assert ids == [a.id for a in rig.store.of_type("grade_draft")]
    assert len(ids) == 1


async def test_gateway_collects_no_id_when_the_write_fails(rig):
    rig.store.fail = True
    ids: list[str] = []
    await rig.gateway.invoke(replace(rig.ctx(), ai_action_ids=ids), "grading_assistant",
                             "assessments.draft_grade", _draft(2), call_id="tu1")
    assert ids == []


# --- attestation and badge eligibility ---------------------------------------------------


async def test_attestation_and_badge_recommendation_then_approval(rig, world):
    student = world.people["student"].id
    await rig.call("attestations.attest", {"person_id": student, "node_id": CONCEPT,
                                           "level": "mastery"},
                   agent="tutor", person="student", call_id="tu1")

    [attestation] = rig.store.of_type("attestation")
    assert (attestation.target_type, attestation.target_id) == ("attestations", ATTESTATION)
    assert attestation.subject_person == student
    assert attestation.output["level"] == "mastery"
    assert ("node", CONCEPT) in {(s["type"], s["id"]) for s in attestation.sources}
    [recommendation] = rig.store.of_type("recommendation")
    assert (recommendation.target_type, recommendation.target_id) == (
        "pending_credentials", PENDING)
    assert recommendation.output["microcredential_id"] == MICRO

    await rig.gated("assessments.approve_credential",
                    {"pending_id": PENDING, "reviewer_id": "x"}, "approve",
                    agent="assessment", call_id="tu2")
    [decision] = rig.store.decisions_on(recommendation.id)
    assert (decision.decision, decision.decided_by) == ("accepted",
                                                        world.people["faculty"].id)


async def test_rejecting_a_badge_approval_rejects_the_recommendation(rig, world):
    await rig.call("attestations.attest", {"person_id": world.people["student"].id,
                                           "node_id": CONCEPT, "level": "mastery"},
                   agent="tutor", person="student", call_id="tu1")
    await rig.gated("assessments.approve_credential",
                    {"pending_id": PENDING, "reviewer_id": "x"}, "reject",
                    agent="assessment", call_id="tu2")
    [recommendation] = rig.store.of_type("recommendation")
    assert [d.decision for d in rig.store.decisions_on(recommendation.id)] == ["rejected"]


# --- profile updates and generation ------------------------------------------------------


async def test_analyst_profile_update_through_the_gateway(rig, world):
    student = world.people["student"].id
    await rig.call("roster.update_learner_profile",
                   {"person_id": student, "profile_md": "Likes examples."},
                   agent="learning_analyst", person="student", call_id="tu1")
    [action] = rig.store.of_type("profile_update")
    assert action.subject_person == student
    assert action.output["profile_md"] == "Likes examples."


async def test_skill_document_save_is_a_generation(rig):
    await rig.call("content.save_skill", {"concept_id": CONCEPT, "body_md": "# Recursion"},
                   agent="content_generator", call_id="tu1")
    [action] = rig.store.of_type("generation")
    assert (action.target_type, action.target_id) == ("content_items", QUESTION)
    assert action.output["body_md"] == "# Recursion"
    assert rig.store.decided == []


async def test_published_question_with_an_edit_records_what_was_changed(rig):
    question = {"bank_id": BANK, "type": "mcq", "stem": "2+2?", "answer_key": {"a": 4}}
    await rig.gated("assessments.create_question", question, "edit", agent="assessment",
                    call_id="tu1", edited={**question, "stem": "What is 2 + 2?"})
    [action] = rig.store.of_type("generation")
    assert action.output["stem"] == "2+2?"
    [decision] = rig.store.decisions_on(action.id)
    assert decision.decision == "edited"
    assert decision.diff is not None and set(decision.diff["fields"]) == {"stem"}


async def test_declined_question_is_still_recorded_and_rejected(rig):
    question = {"bank_id": BANK, "type": "mcq", "stem": "2+2?", "answer_key": {"a": 4}}
    await rig.gated("assessments.create_question", question, "reject", agent="assessment",
                    call_id="tu1")
    [action] = rig.store.of_type("generation")
    assert action.target_id is None
    assert [d.decision for d in rig.store.decisions_on(action.id)] == ["rejected"]


# --- runner: model, prompt hash and tool-use id ------------------------------------------


class FakeAnthropic:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


def _usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=10, output_tokens=5)


async def test_runner_records_the_model_and_the_prompt_behind_the_call(rig, monkeypatch):
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    client = FakeAnthropic([
        SimpleNamespace(stop_reason="tool_use", usage=_usage(), content=[
            SimpleNamespace(type="tool_use", id="toolu_1", name="assessments_draft_grade",
                            input=_draft(2))]),
        SimpleNamespace(stop_reason="end_turn", usage=_usage(),
                        content=[SimpleNamespace(type="text", text="Drafted.")]),
    ])
    runner = ClaudeAgentRunner(model="claude-test-model", client=client,  # type: ignore[arg-type]
                               gateway=rig.gateway)
    ctx = GatewayContext(auth=auth_context(rig.world, "faculty"), session_id=SESSION,
                         turn_id="turn-9", course_id=CS101.course_id)
    await runner.run("grading_assistant", {"message": "grade it", "persona": "faculty",
                                           "_tool_context": ctx})

    [action] = rig.store.of_type("grade_draft")
    sent = client.requests[0]
    assert action.model == "claude-test-model"
    assert action.prompt_sha256 == prompt_sha256(sent["system"], sent["messages"])
    assert action.id == stable_id(f"{turn_db_id('turn-9')}:toolu_1", "grade_draft", "")


# --- analyst (background) ----------------------------------------------------------------


async def test_background_analyst_records_profile_updates(monkeypatch, world):
    student = world.people["student"].id
    store = InMemoryProvenanceStore()

    async def call_mcp(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "roster.get_session_transcript":
            return {"turns": [{"role": "user", "content": "hi"}]}
        if tool.startswith("roster.update"):
            return {"updated": True}
        return {}

    reply = json.dumps({"session_summary": "", "profile_additions": "Prefers visuals.",
                        "student_insights": ["You learn well from diagrams."],
                        "review_flag": False, "concepts_reviewed": []})
    client = FakeAnthropic([SimpleNamespace(content=[SimpleNamespace(text=reply)])])
    monkeypatch.setattr(runner_mod, "_call_mcp_json", call_mcp)
    monkeypatch.setattr(analyst, "make_anthropic_client", lambda: client)
    monkeypatch.setattr(analyst.random, "random", lambda: 0.99)

    await analyst.run_session_analysis(SESSION, student, CS101.course_id,
                                       provenance=ProvenanceRecorder(store))

    actions = store.of_type("profile_update")
    assert [a.output["tool"] for a in actions] == ["roster.update_learner_profile",
                                                  "roster.update_student_insights"]
    assert all(a.subject_person == student and a.session_id == SESSION for a in actions)
    assert actions[0].model == "claude-haiku-4-5-20251001"
    assert actions[0].prompt_sha256 is not None


# --- REST --------------------------------------------------------------------------------


@pytest.fixture
def store() -> InMemoryProvenanceStore:
    return InMemoryProvenanceStore()


@pytest.fixture
def auth_app(auth_world, store):
    auth_world.directory.pending[PENDING] = CS101.course_id
    return create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                      provenance=store)


async def _action(store: InMemoryProvenanceStore, action_type: str, **fields: Any) -> str:
    row = AiActionRow(id=str(uuid.uuid4()), agent="tutor", action_type=action_type,  # type: ignore[arg-type]
                      output={}, **fields)
    await store.record_action(row)
    return row.id


async def test_subject_learner_dismisses_a_recommendation(authed_client, auth_world, store):
    action = await _action(store, "recommendation",
                           subject_person=auth_world.people["student"].id)
    client = await authed_client("student")
    resp = await client.post(f"/api/ai-actions/{action}/decisions",
                             json={"decision": "dismissed", "reason": "Not helpful"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["decision"], body["reason"]) == ("dismissed", "Not helpful")
    assert body["decided_by"] == auth_world.people["student"].id
    assert body["decided_by_name"] == "Emma Smith"
    assert [d.decision for d in store.decisions_on(action)] == ["dismissed"]


async def test_snooze_keeps_the_snooze_time(authed_client, auth_world, store):
    action = await _action(store, "nudge", subject_person=auth_world.people["student"].id)
    client = await authed_client("student")
    resp = await client.post(f"/api/ai-actions/{action}/decisions",
                             json={"decision": "snoozed",
                                   "snooze_until": "2026-10-09T09:00:00Z"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["diff"] == {"snooze_until": "2026-10-09T09:00:00+00:00"}


async def test_another_learner_cannot_decide(authed_client, auth_world, store):
    action = await _action(store, "practice_item", subject_person=auth_world.people["noah"].id)
    client = await authed_client("student")
    resp = await client.post(f"/api/ai-actions/{action}/decisions",
                             json={"decision": "accepted"})
    assert resp.status_code == 403


@pytest.mark.parametrize("action_type", ["grade_draft", "criterion_feedback", "attestation",
                                         "generation", "profile_update"])
async def test_items_with_their_own_review_endpoint_are_refused(authed_client, auth_world,
                                                                store, action_type):
    action = await _action(store, action_type, subject_person=auth_world.people["student"].id,
                           course_node=CS101.course_id)
    client = await authed_client("faculty")
    resp = await client.post(f"/api/ai-actions/{action}/decisions",
                             json={"decision": "accepted"})
    assert resp.status_code == 403


async def test_badge_recommendations_are_decided_on_the_credential_endpoint(
        authed_client, auth_world, store):
    action = await _action(store, "recommendation", target_type="pending_credentials",
                           target_id=PENDING, subject_person=auth_world.people["student"].id)
    client = await authed_client("student")
    resp = await client.post(f"/api/ai-actions/{action}/decisions",
                             json={"decision": "accepted"})
    assert resp.status_code == 403


async def test_course_faculty_dismiss_an_alert(authed_client, store):
    action = await _action(store, "alert", course_node=CS101.course_id)
    other = await authed_client("faculty", person="chen")
    assert (await other.post(f"/api/ai-actions/{action}/decisions",
                             json={"decision": "dismissed"})).status_code == 403
    own = await authed_client("faculty")
    assert (await own.post(f"/api/ai-actions/{action}/decisions",
                           json={"decision": "dismissed"})).status_code == 201


async def test_unknown_action_is_404_and_bad_decision_is_422(authed_client, auth_world, store):
    client = await authed_client("student")
    missing = await client.post(f"/api/ai-actions/{uuid.uuid4()}/decisions",
                                json={"decision": "accepted"})
    assert missing.status_code == 404
    action = await _action(store, "nudge", subject_person=auth_world.people["student"].id)
    bad = await client.post(f"/api/ai-actions/{action}/decisions",
                            json={"decision": "edited"})
    assert bad.status_code == 422


async def test_decision_reason_over_2000_chars_is_422(authed_client, auth_world, store):
    action = await _action(store, "nudge", subject_person=auth_world.people["student"].id)
    client = await authed_client("student")
    url = f"/api/ai-actions/{action}/decisions"
    too_long = await client.post(url, json={"decision": "dismissed", "reason": "x" * 2001})
    assert too_long.status_code == 422
    assert store.decisions_on(action) == []
    at_cap = await client.post(url, json={"decision": "dismissed", "reason": "x" * 2000})
    assert at_cap.status_code == 201


async def test_decisions_need_a_session(auth_client, store):
    action = await _action(store, "nudge")
    resp = await auth_client.post(f"/api/ai-actions/{action}/decisions",
                                  json={"decision": "accepted"})
    assert resp.status_code in (401, 403)


async def test_rest_badge_approval_accepts_the_recommendation(authed_client, auth_world,
                                                              store, monkeypatch):
    action = await _action(store, "recommendation", target_type="pending_credentials",
                           target_id=PENDING)

    async def call_mcp(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"approved": True, "credential_id": "c1"}

    monkeypatch.setattr(runner_mod, "_call_mcp_json", call_mcp)
    client = await authed_client("faculty")
    faculty = auth_world.people["faculty"].id
    resp = await client.post(f"/api/approve-credential/{PENDING}",
                             json={"reviewer_id": faculty})
    assert resp.status_code == 200, resp.text
    again = await client.post(f"/api/approve-credential/{PENDING}",
                              json={"reviewer_id": faculty})
    assert again.status_code == 200
    assert [(d.decision, d.decided_by) for d in store.decisions_on(action)] == [
        ("accepted", faculty)]


async def test_failed_rest_badge_approval_writes_no_decision(authed_client, auth_world,
                                                             store, monkeypatch):
    action = await _action(store, "recommendation", target_type="pending_credentials",
                           target_id=PENDING)

    async def call_mcp(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"error": "Pending credential not found"}

    monkeypatch.setattr(runner_mod, "_call_mcp_json", call_mcp)
    client = await authed_client("faculty")
    await client.post(f"/api/approve-credential/{PENDING}",
                      json={"reviewer_id": auth_world.people["faculty"].id})
    assert store.decisions_on(action) == []


# --- podcast -----------------------------------------------------------------------------


async def test_podcast_script_is_recorded_as_a_generation(monkeypatch, world):
    # engine.podcast creates /app/audio on import, which only exists in the container.
    monkeypatch.delitem(sys.modules, "engine.podcast", raising=False)
    with monkeypatch.context() as patched:
        patched.setattr(Path, "mkdir", lambda *_, **__: None)
        podcast = importlib.import_module("engine.podcast")

    async def script(*_: Any) -> str:
        return "HOST: Hi.\nEXPERT: Recursion calls itself."

    async def audio(_: Any, podcast_id: str) -> str:
        return f"/audio/{podcast_id}.txt"

    monkeypatch.setattr(podcast, "generate_podcast_script", script)
    monkeypatch.setattr(podcast, "render_audio", audio)
    store = InMemoryProvenanceStore()
    student = world.people["student"].id

    result = await podcast.generate_podcast(
        [{"id": CONCEPT, "title": "Recursion", "body_md": "..."}], "CS 101", "1/5", "",
        provenance=ProvenanceRecorder(store), person_id=student, course_id=CS101.course_id,
        session_id=SESSION)

    [action] = store.of_type("generation")
    assert action.target_type == "podcasts"
    assert action.target_id == result["podcast_id"]
    assert action.subject_person == student
    assert action.output["script"] == result["script"]
    assert action.sources == [{"type": "node", "id": CONCEPT, "version": None}]
    assert action.model == podcast.PODCAST_MODEL
