"""ToolGateway step 5 (write-gate) and the approval resume, unit and live-path E2E."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

import engine.agents.runner as runner_mod
from engine.agents.runner import ClaudeAgentRunner, _with_backstop
from engine.app import create_app
from engine.graph.dispatch import set_agent_runner
from engine.graph.interpret import set_llm_client
from engine.guardrails.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalTimeoutError,
)
from engine.guardrails.budget import ActiveClock, BudgetConfig, BudgetTracker
from engine.guardrails.gateway import (
    EditRejected,
    GatewayContext,
    PermissionDenied,
    ScopeDenied,
    ToolGateway,
)
from engine.models.turn import Turn
from engine.tests.auth_fakes import CS101, AuthWorld, auth_context, build_auth_world
from engine.tests.object_fakes import InMemoryObjectDirectory
from engine.turn_repository import ToolCallRow


def _objects() -> InMemoryObjectDirectory:
    return InMemoryObjectDirectory(submissions={"sub1": CS101.course_id, "s": CS101.course_id},
                                   banks={"b1": CS101.course_id})


@pytest.fixture
def auth_app(auth_world):
    return create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                      object_directory=_objects())

COMMITTED = json.dumps({"committed": True, "committed_at": "2026-10-02T12:00:00Z"})
INSTRUCTOR = {"final_scores": {"c1": 4}, "holistic_md": "Well argued; cite one more source."}
COMMIT_EDIT = {"grade_id": "g1", **INSTRUCTOR}


class FakeMcp:
    """Stands in for every MCP server; records calls by tool name.

    Every submission belongs to `student_id`; `responses` overrides a tool's reply."""

    def __init__(self, student_id: str = "", responses: dict[str, Any] | None = None) -> None:
        self.student_id = student_id
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, dict(args)))
        if tool in self.responses:
            return json.dumps(self.responses[tool])
        if tool == "roster.get_recent_turns":
            return json.dumps({"turns": []})
        if tool == "assessments.commit_grade":
            return COMMITTED
        if tool == "assessments.draft_grade":
            return json.dumps({"grade_id": "g1"})
        if tool == "assessments.get_submission":
            return json.dumps({"id": args["submission_id"], "person_id": self.student_id,
                               "assignment_node": "a1", "submitted_at": "2026-09-30T10:00:00Z"})
        if tool == "roster.get":
            return json.dumps({"id": args["person_id"], "display_name": "Emma Smith",
                               "roles": ["student"]})
        return json.dumps({"ok": True})

    def calls_to(self, tool: str) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == tool]


class Turns:
    def __init__(self) -> None:
        self.rows: list[ToolCallRow] = []

    async def record_tool_call(self, row: ToolCallRow) -> bool:
        self.rows.append(row)
        return True


class Statuses:
    def __init__(self) -> None:
        self.history: list[str] = []

    async def update_status(self, turn_id: str, status: str) -> None:
        self.history.append(status)


class Events:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def approval_requests(self) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events if e["event"] == "approval_request"]


class FakeAnthropic:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


def _usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=100, output_tokens=50)


def _tool_use(name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="tool_use", usage=_usage(), content=[
        SimpleNamespace(type="tool_use", id="tu1", name=name, input=args)])


def _final(text: str) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="end_turn", usage=_usage(),
                           content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


@pytest.fixture(autouse=True)
def _reset_runner(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    yield
    set_agent_runner(None)
    set_llm_client(None)


class Rig:
    def __init__(self, world: AuthWorld, *, timeout: float = 5.0) -> None:
        self.world = world
        self.mcp = FakeMcp(world.people["student"].id)
        self.turns = Turns()
        self.statuses = Statuses()
        self.events = Events()
        self.gate = ApprovalGate()
        self.objects = _objects()
        self.gateway = ToolGateway(self.mcp, directory=world.directory, objects=self.objects,
                                   turns=self.turns,
                                   approvals=self.gate, turn_status=self.statuses,
                                   approval_timeout=timeout)
        faculty_id = world.people["faculty"].id
        for grade_id in ("g1", "g2"):
            self.gateway.drafts.remember("grade", grade_id, faculty_id,
                                         {"submission_id": "sub1", "scores": {"c1": 3},
                                          "feedback": {"c1": "Clear"}, "graded_by": faculty_id})

    def ctx(self, person: str = "faculty", role: str | None = None, **kw: Any) -> GatewayContext:
        fields: dict[str, Any] = {"session_id": "sess-1", "turn_id": "turn-1", "step_id": "s1",
                                  "course_id": CS101.course_id, "emit": self.events, **kw}
        return GatewayContext(auth=auth_context(self.world, person, role), **fields)

    async def pending(self) -> str:
        for _ in range(100):
            if self.events.approval_requests():
                return str(self.events.approval_requests()[-1]["approval_id"])
            await asyncio.sleep(0)
        raise AssertionError("no approval_request emitted")

    async def decide(self, decision: str, person: str = "faculty",
                     edited: dict[str, Any] | None = None) -> None:
        approval_id = await self.pending()
        approver = auth_context(self.world, person)
        request = self.gate.get_pending(approval_id)
        assert request is not None
        args = edited if edited is not None else request.tool_arguments
        if decision != "reject":
            args = await self.gateway.authorize_approver(request, approver, args)
        self.gate.resolve(ApprovalDecision(approval_id, decision, edited),  # type: ignore[arg-type]
                          approver=approver, tool_arguments=args)


# --- gateway unit tests -------------------------------------------------------------------


async def test_gated_tool_is_held_until_approved(world):
    rig = Rig(world)
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "grading_assistant", "assessments.commit_grade", {"grade_id": "g1"}))

    approval_id = await rig.pending()
    assert rig.mcp.calls_to("assessments.commit_grade") == []
    assert rig.statuses.history == ["awaiting_approval"]
    payload = rig.events.approval_requests()[0]
    assert payload["artifact_type"] == "grade_commit"
    assert payload["step_id"] == "s1"
    assert payload["preview"]["arguments"] == {"grade_id": "g1"}
    assert payload["preview"]["artifact"]["grade"]["scores"] == {"c1": 3}
    assert payload["preview"]["artifact"]["requires"] == {"final_scores": ["c1"],
                                                          "holistic_md": True}
    assert rig.turns.rows[0].outcome == "gated"
    assert rig.turns.rows[0].args["approval_id"] == approval_id

    await rig.decide("edit", edited=COMMIT_EDIT)
    result = await call

    assert result.success
    assert rig.mcp.calls_to("assessments.commit_grade") == [COMMIT_EDIT]
    assert rig.statuses.history == ["awaiting_approval", "active"]
    faculty_id = world.people["faculty"].id
    assert result.approval == {"approval_id": approval_id, "decision": "edit",
                               "approved_by": faculty_id}
    assert rig.turns.rows[-1].outcome == "ok"
    assert rig.turns.rows[-1].args["approved_by"] == faculty_id


async def test_rejected_call_is_not_executed_and_the_model_is_told(world):
    rig = Rig(world)
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "grading_assistant", "assessments.commit_grade", {"grade_id": "g1"}))

    await rig.decide("reject")
    result = await call

    assert rig.mcp.calls_to("assessments.commit_grade") == []
    assert result.outcome == "gated"
    assert "declined" in json.loads(result.text)["reason"]
    assert rig.turns.rows[-1].args["decision"] == "reject"


async def test_edit_executes_the_edited_arguments(world):
    rig = Rig(world)
    question = {"bank_id": "b1", "type": "mcq", "stem": "?", "answer_key": {}}
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "assessment", "assessments.create_question", question))

    await rig.decide("edit", edited={**question, "stem": "What is 2 + 2?"})
    await call

    assert rig.mcp.calls_to("assessments.create_question") == [
        {**question, "stem": "What is 2 + 2?"}]


async def test_create_question_is_gated(world):
    rig = Rig(world)
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "assessment", "assessments.create_question",
        {"bank_id": "b1", "type": "mcq", "stem": "?", "answer_key": {}}))

    await rig.pending()
    assert rig.mcp.calls_to("assessments.create_question") == []
    assert rig.events.approval_requests()[0]["artifact_type"] == "quiz"
    await rig.decide("approve")
    await call
    assert len(rig.mcp.calls_to("assessments.create_question")) == 1


async def test_ungated_tool_runs_without_approval(world):
    rig = Rig(world)
    result = await rig.gateway.invoke(rig.ctx(), "grading_assistant", "assessments.draft_grade",
                                      {"submission_id": "s", "scores": {}, "feedback": {},
                                       "graded_by": "x"})
    assert result.success
    assert rig.events.approval_requests() == []


async def test_gated_tool_without_an_event_sink_is_denied(world):
    rig = Rig(world)
    result = await rig.gateway.invoke(rig.ctx(emit=None), "grading_assistant",
                                      "assessments.commit_grade", {"grade_id": "g1"})
    assert result.outcome == "denied_permission"
    assert rig.mcp.calls_to("assessments.commit_grade") == []


async def test_unanswered_approval_times_out(world):
    rig = Rig(world, timeout=0.01)
    with pytest.raises(ApprovalTimeoutError):
        await rig.gateway.invoke(rig.ctx(), "grading_assistant", "assessments.commit_grade",
                                 {"grade_id": "g1"})
    assert rig.mcp.calls_to("assessments.commit_grade") == []
    assert rig.gate.pending_count == 0
    assert rig.statuses.history == ["awaiting_approval", "active"]


async def test_time_waiting_for_a_person_is_not_charged_to_the_budget(world):
    rig = Rig(world)
    budget = BudgetTracker(BudgetConfig(max_tokens=10_000, max_tool_calls=10,
                                        max_wall_time_ms=50, max_agent_invocations=5))
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(budget=budget), "grading_assistant", "assessments.commit_grade",
        {"grade_id": "g1"}))
    await rig.pending()
    await asyncio.sleep(0.1)
    await rig.decide("edit", edited=COMMIT_EDIT)

    assert (await call).success
    assert budget.wall_time_ms < 50


async def test_resume_rechecks_an_approver_who_skipped_the_endpoint(world):
    rig = Rig(world)
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "grading_assistant", "assessments.commit_grade", {"grade_id": "g1"}))
    approval_id = await rig.pending()

    rig.gate.resolve(ApprovalDecision(approval_id, "approve"),
                     approver=auth_context(world, "chen", "faculty"))
    result = await call

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls_to("assessments.commit_grade") == []


async def test_student_cannot_approve(world):
    rig = Rig(world)
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g1"}, course_id=CS101.course_id)
    with pytest.raises(PermissionDenied):
        await rig.gateway.authorize_approver(request, auth_context(world, "student"),
                                             request.tool_arguments)


async def test_faculty_of_another_course_cannot_approve(world):
    rig = Rig(world)
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g1"}, course_id=CS101.course_id)
    with pytest.raises(ScopeDenied):
        await rig.gateway.authorize_approver(request, auth_context(world, "chen", "faculty"),
                                             request.tool_arguments)


async def test_approval_without_a_known_course_needs_an_admin(world):
    rig = Rig(world)
    del rig.objects.submissions["sub1"]
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g1"}, course_id="all")
    with pytest.raises(ScopeDenied):
        await rig.gateway.authorize_approver(request, auth_context(world, "faculty"),
                                             request.tool_arguments)


async def test_grade_approval_uses_the_submissions_course_not_the_sessions(world):
    rig = Rig(world)
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g1"}, course_id="all")

    args = await rig.gateway.authorize_approver(request, auth_context(world, "faculty"),
                                                {**request.tool_arguments, **INSTRUCTOR})

    assert args["grade_id"] == "g1"


async def test_credential_reviewer_becomes_the_approver(world):
    rig = Rig(world)
    world.directory.pending["p1"] = CS101.course_id
    request = rig.gate.create_request("s1", "assessment", "Approve credential", {},
                                      "credential", "assessments.approve_credential",
                                      {"pending_id": "p1", "reviewer_id": "someone-else"},
                                      course_id="all")
    torres = auth_context(world, "faculty")

    args = await rig.gateway.authorize_approver(request, torres, request.tool_arguments)

    assert args == {"pending_id": "p1", "reviewer_id": torres.person_id}


async def test_backstop_ignores_paused_time():
    clock = ActiveClock()

    async def work() -> dict[str, Any]:
        with clock.pause():
            await asyncio.sleep(0.1)
        return {"ok": True}

    assert await _with_backstop(work(), clock, timeout_s=0.05) == {"ok": True}


async def test_backstop_still_times_out_active_work():
    async def work() -> dict[str, Any]:
        await asyncio.sleep(1)
        return {}

    with pytest.raises(TimeoutError):
        await _with_backstop(work(), ActiveClock(), timeout_s=0.02)


# --- live-path E2E: scenario 3 through /api/converse with a real ClaudeAgentRunner --------


class GradingIntent:
    async def create_message(self, model, system, messages, max_tokens):  # noqa: ANN001
        return json.dumps({
            "action": "grade", "agent": "grading_assistant", "parameters": {},
            "confidence": 0.95, "needs_clarification": False, "clarification_reason": None,
        })


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch, auth_world: AuthWorld) -> SimpleNamespace:
    mcp = FakeMcp(auth_world.people["student"].id)
    monkeypatch.setattr(runner_mod, "_call_mcp_tool", mcp)
    claude = FakeAnthropic([
        _tool_use("assessments_draft_grade", {"submission_id": "sub1", "scores": {"c1": 3},
                                              "feedback": {"c1": "Clear"}, "graded_by": "x"}),
        _tool_use("assessments_commit_grade", {"grade_id": "g1"}),
        _final("Done."),
    ])
    set_llm_client(GradingIntent())
    set_agent_runner(ClaudeAgentRunner(client=claude))
    return SimpleNamespace(mcp=mcp, claude=claude)


async def _start_grading_turn(app: Any, client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/session", json={"course_id": "cs101"})
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["session_id"]
    resp = await client.post("/api/converse", json={
        "session_id": session_id, "message": "Commit the grade for submission g1"})
    assert resp.status_code == 202
    turn_id = resp.json()["turn_id"]
    turn = await _wait_for(app, turn_id, ("awaiting_approval",))
    approvals = [e for e in turn.events if e["event"] == "approval_request"]
    assert len(approvals) == 1
    return {"session_id": session_id, "turn_id": turn_id,
            "approval_id": approvals[0]["payload"]["approval_id"]}


async def _wait_for(app: Any, turn_id: str, statuses: tuple[str, ...]) -> Turn:
    for _ in range(400):
        turn = await app.state.turn_store.get(turn_id)
        if turn is not None and turn.status in statuses:
            return turn  # type: ignore[no-any-return]
        await asyncio.sleep(0.01)
    turn = await app.state.turn_store.get(turn_id)
    raise AssertionError(f"turn stayed {turn.status if turn else None}")


async def test_grading_turn_halts_at_approval_request(auth_app, authed_client, live):
    faculty = await authed_client("faculty")
    ids = await _start_grading_turn(auth_app, faculty)

    turn = await auth_app.state.turn_store.get(ids["turn_id"])
    payload = next(e["payload"] for e in turn.events if e["event"] == "approval_request")
    assert payload["agent"] == "grading_assistant"
    assert payload["artifact_type"] == "grade_commit"
    assert live.mcp.calls_to("assessments.commit_grade") == []
    assert len(live.claude.requests) == 2

    await faculty.post("/api/approval", json={**ids, "decision": "reject"})
    await _wait_for(auth_app, ids["turn_id"], ("completed", "error"))


async def test_approving_commits_once_with_the_approved_args(auth_app, authed_client, live,
                                                             auth_world):
    faculty = await authed_client("faculty")
    ids = await _start_grading_turn(auth_app, faculty)

    resp = await faculty.post("/api/approval", json={**ids, "decision": "edit",
                                                     "edited_payload": COMMIT_EDIT})
    assert resp.status_code == 202
    turn = await _wait_for(auth_app, ids["turn_id"], ("completed", "error"))

    assert turn.status == "completed"
    assert live.mcp.calls_to("assessments.commit_grade") == [COMMIT_EDIT]
    tool_result = live.claude.requests[2]["messages"][-1]["content"][0]["content"]
    assert "committed" in tool_result
    call = next(e["payload"] for e in turn.events if e["event"] == "agent_tool_call"
                and e["payload"]["tool"] == "assessments.commit_grade")
    assert call["success"] is True
    assert turn.events[-1]["event"] == "final"


async def test_rejecting_does_not_commit(auth_app, authed_client, live):
    faculty = await authed_client("faculty")
    ids = await _start_grading_turn(auth_app, faculty)

    resp = await faculty.post("/api/approval", json={**ids, "decision": "reject"})
    assert resp.status_code == 202
    turn = await _wait_for(auth_app, ids["turn_id"], ("completed", "error"))

    assert turn.status == "completed"
    assert live.mcp.calls_to("assessments.commit_grade") == []
    tool_result = live.claude.requests[2]["messages"][-1]["content"][0]["content"]
    assert "declined" in tool_result


@pytest.mark.parametrize("person, role", [("student", "student"), ("chen", "faculty")])
async def test_other_people_cannot_approve(auth_app, authed_client, live, person, role):
    faculty = await authed_client("faculty")
    ids = await _start_grading_turn(auth_app, faculty)
    other = await authed_client(role, person=person)

    resp = await other.post("/api/approval", json={**ids, "decision": "approve"})

    assert resp.status_code == 403
    assert auth_app.state.approval_gate.get_pending(ids["approval_id"]) is not None
    assert live.mcp.calls_to("assessments.commit_grade") == []
    await faculty.post("/api/approval", json={**ids, "decision": "reject"})
    await _wait_for(auth_app, ids["turn_id"], ("completed", "error"))


async def test_dispatch_without_a_live_stream_denies_instead_of_waiting(world):
    from engine.graph.dispatch import dispatch

    mcp = FakeMcp()
    claude = FakeAnthropic([_tool_use("assessments_commit_grade", {"grade_id": "g1"}),
                            _final("Could not commit.")])
    set_agent_runner(ClaudeAgentRunner(client=claude))
    gateway = ToolGateway(mcp, directory=world.directory, objects=_objects(),
                          approvals=ApprovalGate())
    state = {
        "session_id": "sess-1", "turn_id": "turn-1", "persona": "faculty",
        "course_id": CS101.course_id, "current_message": "commit g1",
        "auth": auth_context(world, "faculty"), "tool_gateway": gateway,
        "plan": {"steps": [{"step_id": "s1", "agent": "grading_assistant"}]},
        "events_emitted": [], "agent_results": [],
    }

    result = await asyncio.wait_for(dispatch(state), timeout=5)

    assert mcp.calls == []
    guardrails = [e for e in result["events_emitted"] if e["event"] == "guardrail"]
    assert guardrails[0]["payload"]["tool"] == "assessments.commit_grade"


async def test_grader_becomes_the_approver(world):
    rig = Rig(world)
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g1", "graded_by": "someone-else",
                                       "course_id": CS101.course_id},
                                      course_id=CS101.course_id)
    torres = auth_context(world, "faculty")

    args = await rig.gateway.authorize_approver(request, torres,
                                                {**request.tool_arguments, **INSTRUCTOR})

    assert args["graded_by"] == torres.person_id


# --- commit_grade needs the instructor's final scores and closing comment (spec.md §7.9) --


async def test_final_scores_the_model_proposes_never_reach_the_commit(world):
    rig = Rig(world)
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "grading_assistant", "assessments.commit_grade",
        {"grade_id": "g1", "final_scores": {"c1": 3}, "holistic_md": "Model's comment"}))

    approval_id = await rig.pending()
    assert rig.gate.get_pending(approval_id).tool_arguments == {"grade_id": "g1"}
    with pytest.raises(EditRejected):
        await rig.decide("approve")
    rig.gate.resolve(ApprovalDecision(approval_id, "reject"),
                     approver=auth_context(world, "faculty"))
    await call
    assert rig.mcp.calls_to("assessments.commit_grade") == []


async def test_a_resume_without_instructor_inputs_is_refused_and_nothing_commits(world):
    rig = Rig(world)
    call = asyncio.create_task(rig.gateway.invoke(
        rig.ctx(), "grading_assistant", "assessments.commit_grade", {"grade_id": "g1"}))
    approval_id = await rig.pending()

    rig.gate.resolve(ApprovalDecision(approval_id, "approve"),
                     approver=auth_context(world, "faculty"),
                     tool_arguments={"grade_id": "g1"})
    result = await call

    assert result.outcome == "denied_policy"
    assert "final score" in result.guardrail["reason"]
    assert rig.mcp.calls_to("assessments.commit_grade") == []


async def test_every_rubric_criterion_needs_a_final_score(world):
    rig = Rig(world)
    rig.gateway.drafts.remember("grade", "g3", world.people["faculty"].id,
                                {"submission_id": "sub1", "rubric_id": "r1",
                                 "scores": {"Thesis": 3}})
    rig.mcp.responses["assessments.get_rubric"] = {"id": "r1", "criteria": [
        {"name": "Thesis"}, {"name": "Writing Mechanics"}]}
    request = rig.gate.create_request("s1", "grading_assistant", "Commit grade", {},
                                      "grade_commit", "assessments.commit_grade",
                                      {"grade_id": "g3"}, course_id=CS101.course_id)
    faculty = auth_context(world, "faculty")
    comment = {"holistic_md": "Good work."}

    with pytest.raises(EditRejected, match="Writing Mechanics"):
        await rig.gateway.authorize_approver(
            request, faculty, {"grade_id": "g3", "final_scores": {"thesis": 3}, **comment})
    args = await rig.gateway.authorize_approver(
        request, faculty,
        {"grade_id": "g3", "final_scores": {"thesis": 3, "writing_mechanics": 2}, **comment})

    assert args["final_scores"] == {"Thesis": 3, "Writing Mechanics": 2}
