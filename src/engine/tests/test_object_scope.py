"""ToolGateway object-level scope for id-keyed tools, audiences, nested identity keys, and the
approval preview."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from engine.auth.directory import SessionOwner
from engine.guardrails.approval import ApprovalDecision, ApprovalGate
from engine.guardrails.gateway import PermissionDenied, EditRejected, GatewayContext, ScopeDenied, ToolGateway
from engine.guardrails.pii import pseudonym
from engine.tests.auth_fakes import (
    CS101,
    ENG102,
    MATH201,
    AuthWorld,
    auth_context,
    build_auth_world,
    fast_password_service,
)
from engine.tests.object_fakes import InMemoryObjectDirectory

Reply = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]


class FakeMcp:
    def __init__(self, replies: dict[str, Reply] | None = None) -> None:
        self.replies: dict[str, Reply] = dict(replies or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, dict(args)))
        reply = self.replies.get(tool, {"ok": True})
        return json.dumps(reply(args) if callable(reply) else reply)

    def calls_to(self, tool: str) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == tool]


class Events:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def previews(self) -> list[dict[str, Any]]:
        return [e["payload"]["preview"] for e in self.events if e["event"] == "approval_request"]


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


def _submissions(world: AuthWorld) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """sub-emma (CS 101) and sub-emma-math (MATH 201) belong to the student enrolled in both;
    sub-noah to the ENG 102 one."""
    owners = {"sub-emma": world.people["student"].id,
              "sub-emma-math": world.people["student"].id,
              "sub-noah": world.people["noah"].id}

    def reply(args: dict[str, Any]) -> dict[str, Any]:
        owner = owners.get(args["submission_id"])
        if owner is None:
            return {"error": "Submission not found"}
        return {"id": args["submission_id"], "person_id": owner, "assignment_node": "a1",
                "submitted_at": "2026-09-30T10:00:00Z", "body_md": "essay"}
    return reply


class Rig:
    def __init__(self, world: AuthWorld, replies: dict[str, Reply] | None = None) -> None:
        self.world = world
        self.mcp = FakeMcp({"assessments.get_submission": _submissions(world),
                            **(replies or {})})
        self.events = Events()
        self.gate = ApprovalGate()
        self.objects = InMemoryObjectDirectory(
            submissions={"sub-emma": CS101.course_id, "sub-emma-math": MATH201.course_id,
                         "sub-noah": ENG102.course_id},
            banks={"b1": CS101.course_id, "b-eng": ENG102.course_id})
        self.gateway = ToolGateway(self.mcp, directory=world.directory, objects=self.objects,
                                   approvals=self.gate, approval_timeout=5)

    def ctx(self, person: str, role: str | None = None) -> GatewayContext:
        return GatewayContext(auth=auth_context(self.world, person, role), session_id="sess-1",
                              turn_id="turn-1", step_id="s1", course_id=CS101.course_id,
                              emit=self.events)

    async def invoke(self, person: str, agent: str, tool: str, args: dict[str, Any],
                     role: str | None = None) -> Any:
        return await self.gateway.invoke(self.ctx(person, role), agent, tool, args)

    async def held(self, person: str, agent: str, tool: str, args: dict[str, Any]
                   ) -> tuple[asyncio.Task[Any], dict[str, Any]]:
        """Start a gated call and return it with the approval_request preview."""
        task = asyncio.create_task(self.invoke(person, agent, tool, args))
        for _ in range(100):
            if self.events.previews():
                return task, self.events.previews()[-1]
            if task.done():
                raise AssertionError(f"call finished without approval: {task.result()}")
            await asyncio.sleep(0)
        raise AssertionError("no approval_request emitted")

    def reject_all(self) -> None:
        for event in self.events.events:
            if event["event"] == "approval_request":
                self.gate.resolve(ApprovalDecision(event["payload"]["approval_id"], "reject"))


# --- submissions and grades --------------------------------------------------------------


async def test_student_reads_only_their_own_submission(world):
    rig = Rig(world)

    own = await rig.invoke("student", "grading_assistant", "assessments.get_submission",
                           {"submission_id": "sub-emma"})
    other = await rig.invoke("noah", "grading_assistant", "assessments.get_submission",
                             {"submission_id": "sub-emma"}, role="student")

    assert own.success
    assert other.outcome == "denied_scope"


async def test_faculty_cannot_read_or_draft_for_a_submission_outside_their_courses(world):
    rig = Rig(world)

    read = await rig.invoke("faculty", "grading_assistant", "assessments.get_submission",
                            {"submission_id": "sub-noah"})
    draft = await rig.invoke("faculty", "grading_assistant", "assessments.draft_grade",
                             {"submission_id": "sub-noah", "scores": {}, "feedback": {},
                              "graded_by": "x"})

    assert (read.outcome, draft.outcome) == ("denied_scope", "denied_scope")
    assert rig.mcp.calls_to("assessments.draft_grade") == []


async def test_faculty_cannot_grade_a_shared_student_in_a_course_they_do_not_teach(world):
    rig = Rig(world)

    read = await rig.invoke("faculty", "grading_assistant", "assessments.get_submission",
                            {"submission_id": "sub-emma-math"})
    draft = await rig.invoke("faculty", "grading_assistant", "assessments.draft_grade",
                             {"submission_id": "sub-emma-math", "scores": {}, "feedback": {},
                              "graded_by": "x"})

    assert (read.outcome, draft.outcome) == ("denied_scope", "denied_scope")
    assert rig.mcp.calls_to("assessments.draft_grade") == []


async def test_commit_of_a_grade_in_another_course_is_denied(world):
    rig = Rig(world, {"assessments.draft_grade": {"grade_id": "g-cs"}})
    drafted = await rig.invoke("faculty", "grading_assistant", "assessments.draft_grade",
                               {"submission_id": "sub-emma", "scores": {}, "feedback": {},
                                "graded_by": "x"})

    commit = await rig.invoke("chen", "grading_assistant", "assessments.commit_grade",
                              {"grade_id": "g-cs"}, role="faculty")

    assert drafted.success
    assert commit.outcome == "denied_scope"
    assert rig.events.previews() == []


async def test_submission_with_no_known_course_is_denied_to_faculty(world):
    rig = Rig(world)
    del rig.objects.submissions["sub-emma"]

    result = await rig.invoke("faculty", "grading_assistant", "assessments.get_submission",
                              {"submission_id": "sub-emma"})

    assert result.outcome == "denied_scope"


@pytest.mark.parametrize("bank, allowed", [("b1", True), ("b-eng", False), ("b-missing", False)])
async def test_create_question_needs_the_banks_course(world, bank, allowed):
    rig = Rig(world)
    args = {"bank_id": bank, "type": "mcq", "stem": "Q?", "answer_key": {"correct": "a"}}

    if allowed:
        task, _ = await rig.held("faculty", "assessment", "assessments.create_question", args)
        rig.reject_all()
        await task
    else:
        result = await rig.invoke("faculty", "assessment", "assessments.create_question", args)
        assert result.outcome == "denied_scope"
        assert rig.events.previews() == []


async def test_unknown_submission_is_denied(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "grading_assistant", "assessments.get_submission",
                              {"submission_id": "sub-missing"})

    assert result.outcome == "denied_scope"


async def test_faculty_reads_a_submission_in_their_course(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "grading_assistant", "assessments.get_submission",
                              {"submission_id": "sub-emma"})

    assert result.success
    assert len(rig.mcp.calls_to("assessments.get_submission")) == 2


async def test_commit_of_a_grade_the_gateway_never_drafted_is_denied(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "grading_assistant", "assessments.commit_grade",
                              {"grade_id": "g-unknown"})

    assert result.outcome == "denied_scope"
    assert rig.events.previews() == []


async def test_commit_of_a_grade_for_another_courses_submission_is_denied(world):
    rig = Rig(world)
    rig.gateway.drafts.remember("grade", "g-noah", world.people["admin"].id,
                                {"submission_id": "sub-noah"})

    result = await rig.invoke("faculty", "grading_assistant", "assessments.commit_grade",
                              {"grade_id": "g-noah"})

    assert result.outcome == "denied_scope"


async def test_draft_then_commit_shows_the_drafted_grade_in_the_preview(world):
    rig = Rig(world, {"assessments.draft_grade": {"grade_id": "g1"},
                      "roster.get": {"id": "x", "display_name": "Emma Smith",
                                     "roles": ["student"]}})
    drafted = await rig.invoke("faculty", "grading_assistant", "assessments.draft_grade", {
        "submission_id": "sub-emma", "scores": {"thesis": 3},
        "feedback": {"thesis": "Clear claim."}, "holistic_md": "Solid work overall.",
        "graded_by": "x"})
    assert drafted.success

    task, preview = await rig.held("faculty", "grading_assistant", "assessments.commit_grade",
                                   {"grade_id": "g1"})
    rig.reject_all()
    await task

    artifact = preview["artifact"]
    assert artifact["grade"]["scores"] == {"thesis": 3}
    assert artifact["grade"]["submission_id"] == "sub-emma"
    assert "Solid work overall." in artifact["grade"]["holistic_md"]
    assert artifact["submission"]["assignment_node"] == "a1"
    # grading_assistant's manifest requires display_name, so the real name is kept
    assert artifact["student"]["display_name"] == "Emma Smith"


async def test_a_failed_draft_is_not_remembered(world):
    rig = Rig(world, {"assessments.draft_grade": {"error": "Submission not found"}})
    await rig.invoke("faculty", "grading_assistant", "assessments.draft_grade",
                     {"submission_id": "sub-emma", "scores": {}, "feedback": {},
                      "graded_by": "x"})

    assert rig.gateway.drafts.get("grade", "g1") is None


async def test_approver_is_object_scope_checked(world):
    rig = Rig(world)
    rig.gateway.drafts.remember("grade", "g-noah", "x", {"submission_id": "sub-noah"})
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g-noah"}, course_id=CS101.course_id)

    with pytest.raises(ScopeDenied):
        await rig.gateway.authorize_approver(request, auth_context(world, "faculty"),
                                             request.tool_arguments)


async def test_approver_edit_may_not_swap_the_grade(world):
    rig = Rig(world)
    rig.gateway.drafts.remember("grade", "g1", "x", {"submission_id": "sub-emma"})
    rig.gateway.drafts.remember("grade", "g2", "x", {"submission_id": "sub-emma"})
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g1"}, course_id=CS101.course_id)

    with pytest.raises(EditRejected):
        await rig.gateway.authorize_approver(request, auth_context(world, "faculty"),
                                             {"grade_id": "g2"})


@pytest.mark.parametrize("key, before, after", [
    ("aligned_nodes", ["c-cs"], ["c-eng"]),
    ("content_id", "ci-1", "ci-2"),
    ("attestation_id", "at-1", "at-2"),
])
async def test_approver_edit_may_not_swap_linked_objects(world, key, before, after):
    rig = Rig(world)
    original = {"bank_id": "b1", "type": "mcq", "stem": "s", "answer_key": {}, key: before}
    request = rig.gate.create_request("s1", "assessment", "Add question", {},
                                      "question_create", "assessments.create_question",
                                      original, course_id=CS101.course_id)

    with pytest.raises(EditRejected):
        await rig.gateway.authorize_approver(request, auth_context(world, "faculty"),
                                             {**original, key: after})


async def test_edit_resumed_without_the_endpoint_is_rechecked(world):
    rig = Rig(world)
    rig.gateway.drafts.remember("grade", "g1", "x", {"submission_id": "sub-emma"})
    rig.gateway.drafts.remember("grade", "g2", "x", {"submission_id": "sub-emma"})
    task, _ = await rig.held("faculty", "grading_assistant", "assessments.commit_grade",
                             {"grade_id": "g1"})
    approval_id = rig.events.events[-1]["payload"]["approval_id"]

    rig.gate.resolve(ApprovalDecision(approval_id, "edit", {"grade_id": "g2"}),
                     approver=auth_context(world, "faculty"))
    result = await task

    assert result.outcome == "denied_policy"
    assert rig.mcp.calls_to("assessments.commit_grade") == []


# --- messages ------------------------------------------------------------------------------


def _draft_reply(draft_id: str = "d1") -> dict[str, Any]:
    return {"draft_id": draft_id}


async def test_send_of_someone_elses_draft_is_denied(world):
    rig = Rig(world)
    rig.gateway.drafts.remember("message", "d1", world.people["chen"].id,
                                {"channel": "inbox", "audience": {"course_id": CS101.course_id}})

    result = await rig.invoke("faculty", "communication", "communications.send_message",
                              {"draft_id": "d1"})

    assert result.outcome == "denied_scope"
    assert rig.events.previews() == []


async def test_send_of_an_unknown_draft_is_denied(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "communication", "communications.send_message",
                              {"draft_id": "d-unknown"})

    assert result.outcome == "denied_scope"


async def test_send_preview_shows_the_drafted_message_and_recipient_count(world):
    rig = Rig(world, {
        "communications.draft_message": _draft_reply(),
        "roster.list_by_course": {"persons": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]},
    })
    drafted = await rig.invoke("faculty", "communication", "communications.draft_message", {
        "author_id": "x", "channel": "announcement",
        "audience": {"course_id": CS101.course_id, "role": "student"},
        "subject": "Quiz moved", "body_md": "The quiz moves to Friday. SSN 123-45-6789."})
    assert drafted.success

    task, preview = await rig.held("faculty", "communication", "communications.send_message",
                                   {"draft_id": "d1"})
    rig.reject_all()
    await task

    message = preview["artifact"]["message"]
    assert message["channel"] == "announcement"
    assert message["body_md"].startswith("<user_content")
    assert "123-45-6789" not in message["body_md"]
    assert "Quiz moved" in message["subject"]
    assert preview["artifact"]["recipient_count"] == 3
    assert rig.mcp.calls_to("roster.list_by_course") == [
        {"course_id": CS101.course_id, "role": "student"}]


# --- message audience -----------------------------------------------------------------------


@pytest.mark.parametrize("person, audience, allowed", [
    ("faculty", {"course_id": CS101.course_id}, True),
    ("faculty", {"course_id": ENG102.course_id}, False),
    ("faculty", {"course_id": CS101.course_id, "person_ids": ["noah"]}, False),
    ("faculty", {"person_ids": ["student"]}, True),
    ("faculty", {}, False),
    ("faculty", {"role": "student"}, False),
    ("faculty", json.dumps({"course_id": ENG102.course_id}), False),
    ("faculty", "everyone", False),
    ("advisor", {"course_id": CS101.course_id, "person_ids": ["student"]}, True),
    ("advisor", {"course_id": ENG102.course_id}, False),
    ("advisor", {"course_id": CS101.course_id}, False),
    ("advisor", {"course_id": CS101.course_id, "role": "student"}, False),
    ("advisor", {"person_ids": ["noah"]}, False),
    ("advisor", {"course_id": "all"}, False),
    ("advisor", ["noah"], False),
    ("admin", {}, True),
])
async def test_draft_message_audience_is_scope_checked(world, person, audience, allowed):
    rig = Rig(world, {"communications.draft_message": _draft_reply()})

    def ids(value: Any) -> Any:
        if isinstance(value, dict) and "person_ids" in value:
            return {**value, "person_ids": [world.people[p].id for p in value["person_ids"]]}
        if isinstance(value, list):
            return [world.people[p].id for p in value]
        return value

    result = await rig.invoke(person, "communication", "communications.draft_message", {
        "author_id": "x", "channel": "inbox", "audience": ids(audience), "body_md": "Hi"})

    assert result.success is allowed, result.text
    assert bool(rig.mcp.calls_to("communications.draft_message")) is allowed


async def test_audience_json_text_is_sent_as_an_object(world):
    rig = Rig(world, {"communications.draft_message": _draft_reply()})

    await rig.invoke("faculty", "communication", "communications.draft_message", {
        "author_id": "x", "channel": "inbox",
        "audience": json.dumps({"course_id": CS101.course_id}), "body_md": "Hi"})

    assert rig.mcp.calls_to("communications.draft_message")[0]["audience"] == {
        "course_id": CS101.course_id}


# --- credentials ---------------------------------------------------------------------------


def _evidence(world: AuthWorld) -> dict[str, Any]:
    return {"pending_id": "p1", "student_name": "Emma Smith", "credential_title": "Loops",
            "created_at": "2026-09-01T00:00:00Z", "session_count": 4,
            "concepts": [{"id": "c1", "title": "For", "level": "mastery"},
                         {"id": "c2", "title": "While", "level": "proficient"},
                         {"id": "c3", "title": "Do", "level": "mastery"}]}


@pytest.mark.parametrize("person, role", [("advisor", None), ("chen", "faculty")])
async def test_only_course_faculty_or_admin_may_ask_to_approve_a_credential(
        world, person, role):
    world.directory.pending["p1"] = CS101.course_id
    rig = Rig(world)

    result = await rig.invoke(person, "assessment", "assessments.approve_credential",
                              {"pending_id": "p1", "reviewer_id": "x"}, role=role)

    assert result.outcome in ("denied_scope", "denied_permission")
    assert rig.events.previews() == []


async def test_advisor_cannot_approve_a_credential_as_approver(world):
    world.directory.pending["p1"] = CS101.course_id
    rig = Rig(world)
    request = rig.gate.create_request("s1", "assessment", "Approve credential", {},
                                      "credential", "assessments.approve_credential",
                                      {"pending_id": "p1", "reviewer_id": "x"},
                                      course_id=CS101.course_id)

    with pytest.raises((ScopeDenied, PermissionDenied)):
        await rig.gateway.authorize_approver(request, auth_context(world, "advisor"),
                                             request.tool_arguments)


async def test_credential_preview_summarises_the_evidence_with_a_pseudonym(world):
    world.directory.pending["p1"] = CS101.course_id
    rig = Rig(world, {"assessments.get_credential_evidence": _evidence(world)})

    task, preview = await rig.held("faculty", "assessment", "assessments.approve_credential",
                                   {"pending_id": "p1", "reviewer_id": "x"})
    rig.reject_all()
    await task

    artifact = preview["artifact"]
    assert artifact["credential"]["credential_title"] == "Loops"
    assert artifact["credential"]["student_name"] == pseudonym("Emma Smith")
    assert artifact["evidence"]["levels"] == {"mastery": 2, "proficient": 1}
    assert artifact["evidence"]["session_count"] == 4


async def test_credential_evidence_needs_scope_over_the_learner(world):
    world.directory.pending["p1"] = CS101.course_id
    pending = {"pending": [{"id": "p1", "person_id": world.people["noah"].id}]}
    rig = Rig(world, {"assessments.list_pending_credentials": pending})

    result = await rig.invoke("advisor", "assessment", "assessments.get_credential_evidence",
                              {"pending_id": "p1"})

    assert result.outcome == "denied_scope"


async def test_question_preview_shows_the_question(world):
    rig = Rig(world)
    task, preview = await rig.held("faculty", "assessment", "assessments.create_question", {
        "bank_id": "b1", "type": "mcq", "stem": "What does a for loop repeat over?",
        "answer_key": {"correct": "b"}})
    rig.reject_all()
    await task

    question = preview["artifact"]["question"]
    assert "What does a for loop repeat over?" in question["stem"]
    assert question["answer_key"] == {"correct": "b"}


# --- sessions and concepts -----------------------------------------------------------------


async def test_session_tools_check_the_session_owner(world):
    noah, emma = world.people["noah"].id, world.people["student"].id
    world.directory.sessions["s-noah"] = SessionOwner(noah, ENG102.course_id)
    world.directory.sessions["s-emma"] = SessionOwner(emma, CS101.course_id)
    rig = Rig(world)

    other = await rig.invoke("student", "learning_analyst", "roster.get_session_transcript",
                             {"session_id": "s-noah"})
    summary = await rig.invoke("student", "learning_analyst", "roster.update_session_summary",
                               {"session_id": "s-noah", "summary": "x"})
    unknown = await rig.invoke("student", "learning_analyst", "roster.get_session_transcript",
                               {"session_id": "s-missing"})
    own = await rig.invoke("student", "learning_analyst", "roster.get_session_transcript",
                           {"session_id": "s-emma"})
    current = await rig.invoke("student", "learning_analyst", "roster.update_session_summary",
                               {"session_id": "sess-1", "summary": "x"})

    assert [r.outcome for r in (other, summary, unknown)] == ["denied_scope"] * 3
    assert own.success and current.success


@pytest.mark.parametrize("tool, agent, args", [
    ("attestations.attest", "tutor", {"node_id": "c1", "level": "mastery"}),
    ("roster.save_concept_review", "learning_analyst", {"concept_id": "c1",
                                                        "outcome": "recalled"}),
])
@pytest.mark.parametrize("supplied", ["", None, "s-emma-old", "s-noah"])
async def test_student_evidence_writes_are_bound_to_the_current_session(
        world, tool, agent, args, supplied):
    world.directory.sessions["s-emma-old"] = SessionOwner(world.people["student"].id,
                                                          CS101.course_id)
    rig = Rig(world)

    result = await rig.invoke("student", agent, tool, {**args, "session_id": supplied})

    assert result.success
    assert [call["session_id"] for call in rig.mcp.calls_to(tool)] == ["sess-1"]


async def test_student_evidence_write_without_a_current_session_is_denied(world):
    rig = Rig(world)
    ctx = GatewayContext(auth=auth_context(world, "student"), turn_id="turn-1")

    result = await rig.gateway.invoke(ctx, "tutor", "attestations.attest",
                                      {"node_id": "c1", "level": "mastery", "session_id": ""})

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls == []


async def test_faculty_reads_transcripts_only_of_their_students(world):
    world.directory.sessions["s-noah"] = SessionOwner(world.people["noah"].id,
                                                      ENG102.course_id)
    world.directory.sessions["s-emma"] = SessionOwner(world.people["student"].id,
                                                      CS101.course_id)
    rig = Rig(world)

    await rig.gateway._check_session(  # noqa: SLF001
        auth_context(world, "faculty"), "roster.get_session_transcript", "s-emma", "", "t")
    with pytest.raises(ScopeDenied):
        await rig.gateway._check_session(  # noqa: SLF001
            auth_context(world, "faculty"), "roster.get_session_transcript", "s-noah", "", "t")


def _concept_graph(args: dict[str, Any]) -> dict[str, Any]:
    parents = {"c-cs": ("m-cs", "module"), "m-cs": (CS101.course_id, "course"),
               "c-eng": ("m-eng", "module"), "m-eng": (ENG102.course_id, "course")}
    parent = parents.get(args["node_id"])
    return {"nodes": [{"id": parent[0], "kind": parent[1], "edge_kind": "part_of"}]
            if parent else []}


@pytest.mark.parametrize("concept, allowed", [("c-cs", True), ("c-eng", False),
                                              ("c-missing", False)])
async def test_skill_writes_need_the_concepts_course(world, concept, allowed):
    rig = Rig(world, {"graph.neighbors": _concept_graph})

    result = await rig.invoke("faculty", "course_architect", "content.save_skill",
                              {"concept_id": concept, "body_md": "notes"})

    assert result.success is allowed
    assert bool(rig.mcp.calls_to("content.save_skill")) is allowed


@pytest.mark.parametrize("node, allowed", [("c-cs", True), ("m-cs", True),
                                           (CS101.course_id, True), ("c-eng", False),
                                           (ENG102.course_id, False), ("c-missing", False)])
async def test_drafts_on_a_node_need_the_nodes_course(world, node, allowed):
    rig = Rig(world, {"graph.neighbors": _concept_graph})

    result = await rig.invoke("faculty", "content_generator", "content.save_draft",
                              {"node_id": node, "kind": "skill", "title": "t", "body_md": "b",
                               "author_id": "x"})

    assert result.success is allowed
    assert bool(rig.mcp.calls_to("content.save_draft")) is allowed


async def test_a_draft_on_no_node_needs_no_course(world):
    rig = Rig(world, {"graph.neighbors": _concept_graph})

    result = await rig.invoke("faculty", "content_generator", "content.save_draft",
                              {"kind": "summary", "title": "t", "body_md": "b",
                               "author_id": "x"})

    assert result.success
    assert rig.mcp.calls_to("graph.neighbors") == []


# --- identity keys at any depth -------------------------------------------------------------


@pytest.mark.parametrize("args", [
    {"concept_id": "c1", "level": "mastery", "evidence": {"session_id": "s-noah"}},
    {"concept_id": "c1", "level": "mastery", "evidence": [{"submission_id": "sub-noah"}]},
])
async def test_nested_object_ids_are_refused(world, args):
    rig = Rig(world)

    result = await rig.invoke("student", "tutor", "attestations.attest",
                              {"person_id": world.people["student"].id, **args})

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls_to("attestations.attest") == []


async def test_deeply_nested_learner_is_scope_checked(world):
    rig = Rig(world)
    noah = world.people["noah"].id

    result = await rig.invoke("faculty", "engagement_analyst", "analytics.query", {
        "scope": {"course_id": CS101.course_id}, "metric": "logins", "window": {},
        "filters": {"cohort": {"members": [{"person_id": noah}]}}})

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls == []


async def test_deeply_nested_course_is_scope_checked(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "engagement_analyst", "analytics.query", {
        "scope": {"course_id": CS101.course_id}, "metric": "logins", "window": {},
        "filters": {"compare": {"course_id": ENG102.course_id}}})

    assert result.outcome == "denied_scope"


async def test_nested_person_lists_are_scope_checked(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "engagement_analyst", "analytics.query", {
        "scope": {"course_id": CS101.course_id}, "metric": "logins", "window": {},
        "filters": {"student_ids": [world.people["student"].id, world.people["noah"].id]}})

    assert result.outcome == "denied_scope"


async def test_nested_learner_uses_the_enclosing_course(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "engagement_analyst", "analytics.query", {
        "scope": {"course_id": CS101.course_id}, "metric": "logins", "window": {},
        "filters": {"cohort": {"members": [{"person_id": world.people["student"].id}]}}})

    assert result.success


async def test_student_nested_subject_must_be_self(world):
    rig = Rig(world)

    result = await rig.invoke("student", "tutor", "roster.get_student_context", {
        "person_id": world.people["student"].id, "course_id": CS101.course_id,
        "options": {"compare": {"student_id": world.people["noah"].id}}})

    assert result.outcome == "denied_scope"


# --- analytics scope bounds ------------------------------------------------------------------


def _emma(world: AuthWorld) -> str:
    return world.people["student"].id


@pytest.mark.parametrize("tool, args", [
    ("analytics.query", {"scope": {}, "metric": "avg_score", "window": {},
                         "breakdown": "person_id"}),
    ("analytics.query", {"metric": "avg_score", "window": {}, "breakdown": "person_id"}),
    ("analytics.query", {"scope": {"course_id": ""}, "metric": "avg_score", "window": {}}),
    ("analytics.query", {"scope": {"course_id": "all"}, "metric": "avg_score", "window": {}}),
    ("analytics.query", {"scope": "{}", "metric": "avg_score", "window": {}}),
    ("analytics.query", {"scope": {}, "cohorts": [{"scope": {"course_id": CS101.course_id}}],
                         "metric": "avg_score", "window": {}}),
    ("analytics.trend", {"scope": {}, "metric": "avg_score", "window": {}, "interval": "day"}),
    ("analytics.cohort_compare", {"scope": {}, "metric": "avg_score", "window": {},
                                  "cohorts": [{"label": "a", "scope": {}}]}),
    ("analytics.cohort_compare", {"scope": {"course_id": CS101.course_id}, "metric": "x",
                                  "window": {}, "cohorts": [{"label": "a"}, "b"]}),
    ("analytics.cohort_compare", {"scope": {}, "metric": "x", "window": {}, "cohorts": [
        {"label": "a", "scope": {"course_id": CS101.course_id}},
        {"label": "b", "scope": {}}]}),
    ("analytics.cohort_compare", {"scope": {}, "metric": "x", "window": {}, "cohorts": []}),
])
@pytest.mark.parametrize("person, agent", [("faculty", "engagement_analyst"),
                                           ("advisor", "early_alert")])
async def test_unbounded_analytics_scope_is_denied(world, person, agent, tool, args):
    rig = Rig(world)

    result = await rig.invoke(person, agent, tool, args)

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls == []


async def test_faculty_analytics_for_a_learner_must_name_the_course(world):
    rig = Rig(world)

    result = await rig.invoke("faculty", "engagement_analyst", "analytics.query", {
        "scope": {"person_id": _emma(world)}, "metric": "avg_score", "window": {}})

    assert result.outcome == "denied_scope"


async def test_advisor_course_scope_alone_is_denied(world):
    rig = Rig(world)

    result = await rig.invoke("advisor", "early_alert", "analytics.query", {
        "scope": {"course_id": CS101.course_id}, "metric": "avg_score", "window": {},
        "breakdown": "person_id"})

    assert result.outcome == "denied_scope"


async def test_cohort_learner_is_checked_against_the_merged_course(world):
    # Teaches CS 101 and ENG 102, so Noah (ENG 102) is viewable, just not within CS 101.
    world.people["both"] = world.repo.add_person(
        fast_password_service(), display_name="Dr. Two", email="two@university.edu",
        roles=("faculty",), enrollments=(replace(CS101, role="faculty"),
                                         replace(ENG102, role="faculty")))
    rig = Rig(world)
    noah = world.people["noah"].id

    result = await rig.invoke("both", "engagement_analyst", "analytics.cohort_compare", {
        "scope": {"course_id": CS101.course_id}, "metric": "x", "window": {},
        "cohorts": [{"label": "a", "scope": {"person_id": noah}}]}, role="faculty")
    in_own_course = await rig.invoke("both", "engagement_analyst", "analytics.cohort_compare", {
        "scope": {"course_id": ENG102.course_id}, "metric": "x", "window": {},
        "cohorts": [{"label": "a", "scope": {"person_id": noah}}]}, role="faculty")

    assert result.outcome == "denied_scope"
    assert in_own_course.success


@pytest.mark.parametrize("person, agent, tool, args", [
    ("faculty", "engagement_analyst", "analytics.query",
     {"scope": {"course_id": CS101.course_id}, "metric": "avg_score", "window": {},
      "breakdown": "person_id"}),
    ("faculty", "engagement_analyst", "analytics.cohort_compare",
     {"scope": {}, "metric": "x", "window": {},
      "cohorts": [{"label": "a", "scope": {"course_id": CS101.course_id}}]}),
    ("advisor", "early_alert", "analytics.trend",
     {"scope": {"person_id": "EMMA"}, "metric": "avg_score", "window": {}, "interval": "day"}),
    ("admin", "engagement_analyst", "analytics.query",
     {"scope": {}, "metric": "avg_score", "window": {}, "breakdown": "person_id"}),
])
async def test_bounded_analytics_scope_is_allowed(world, person, agent, tool, args):
    rig = Rig(world)
    args = json.loads(json.dumps(args).replace("EMMA", _emma(world)))

    result = await rig.invoke(person, agent, tool, args)

    assert result.success
    assert len(rig.mcp.calls_to(tool)) == 1
