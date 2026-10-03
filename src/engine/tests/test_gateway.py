"""ToolGateway steps 1-3, 7 and 10, the manifest-driven runner, and persona routing."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import engine.agents.runner as runner_mod
from engine.agents.runner import ClaudeAgentRunner, StubAgentRunner
from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.graph.dispatch import dispatch, set_agent_runner
from engine.graph.interpret import ROUTABLE_AGENTS, set_llm_client
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.guardrails.registry import (
    get_manifest_registry,
    get_permission_matrix,
    get_tool_roles,
)
from engine.guardrails.tool_roles import parse_allowed_roles, parse_tool_roles
from engine.logging_config import setup_logging
from engine.models.session import Session
from engine.models.turn import Turn
from engine.streaming.events import GuardrailPayload
from engine.tests.auth_fakes import (
    CS101,
    DEMO_PASSWORD,
    ENG102,
    MATH201,
    AuthWorld,
    auth_context,
    build_auth_world,
)
from engine.turn_repository import ToolCallRow

REPO_ROOT = Path(__file__).resolve().parents[3]


class RecordingExecutor:
    def __init__(self, result: str = '{"nodes": []}') -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, dict(args)))
        return self.result


class FakeTurnRepository:
    def __init__(self, *, exists: bool = True, fail: bool = False) -> None:
        self.exists = exists
        self.fail = fail
        self.rows: list[ToolCallRow] = []

    async def record_tool_call(self, row: ToolCallRow) -> bool:
        if self.fail:
            raise ConnectionError("database is down")
        if self.exists:
            self.rows.append(row)
        return self.exists


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


@pytest.fixture
def executor() -> RecordingExecutor:
    return RecordingExecutor()


@pytest.fixture
def turns() -> FakeTurnRepository:
    return FakeTurnRepository()


@pytest.fixture
def gateway(
    world: AuthWorld, executor: RecordingExecutor, turns: FakeTurnRepository,
) -> ToolGateway:
    return ToolGateway(executor, directory=world.directory, turns=turns)


def _ctx(world: AuthWorld, person: str, role: str | None = None) -> GatewayContext:
    return GatewayContext(auth=auth_context(world, person, role), session_id="sess-1",
                          turn_id="turn-1", step_id="s1")


# --- mcp-tools.md parser -------------------------------------------------------------------


def test_role_qualifiers_are_kept_but_the_role_is_the_backticked_name():
    roles, qualifiers = parse_allowed_roles(
        "`faculty`, `student` (own submissions only), `instructional_designer`"
    )
    assert roles == {"faculty", "student", "instructional_designer"}
    assert qualifiers == {"student": "own submissions only"}


def test_bare_words_grant_no_role():
    assert parse_allowed_roles("none (server-internal: called only by `x`)")[0] == frozenset()
    assert parse_allowed_roles("engine-internal")[0] == frozenset()


def test_planned_and_not_implemented_sections_are_ignored():
    text = (
        "### `a.one`\n- Allowed roles: `student`\n\n"
        "## Planned (Round 2)\n### `a.two`\n- Allowed roles: `faculty`\n"
        "## Not implemented (candidates)\n### `a.three`\n- Allowed roles: `admin`\n"
    )
    assert set(parse_tool_roles(text)) == {"a.one"}


def test_real_contract_parses():
    roles = get_tool_roles()
    assert roles["assessments.commit_grade"].allowed_roles == {"faculty"}
    assert roles["assessments.check_pending_credentials"].allowed_roles == frozenset()
    assert "policy.set" not in roles  # planned, not served


def test_every_live_manifest_tool_has_documented_roles():
    roles = get_tool_roles()
    registry = get_manifest_registry()
    missing = [
        (agent, tool)
        for agent in registry.list_agents()
        for tool in registry.get_manifest(agent).mcp_tools
        if tool not in roles
    ]
    assert missing == []


# --- step 1: allow-list ----------------------------------------------------------------------


async def test_tool_outside_the_agent_manifest_is_denied(gateway, world, executor, turns):
    result = await gateway.invoke(_ctx(world, "faculty"), "tutor", "assessments.commit_grade",
                                  {"submission_id": "x"})

    assert result.outcome == "denied_permission"
    assert json.loads(result.text)["error"] == "not permitted"
    assert result.guardrail == {
        "kind": "denied_permission", "step_id": "s1", "agent": "tutor",
        "tool": "assessments.commit_grade", "reason": result.guardrail["reason"],
    }
    assert executor.calls == []
    assert turns.rows[0].outcome == "denied_permission"


async def test_planned_tool_is_not_callable_yet(gateway, world, executor):
    result = await gateway.invoke(_ctx(world, "faculty"), "course_architect",
                                  "content.publish", {})

    assert result.outcome == "denied_permission"
    assert executor.calls == []


async def test_agent_without_manifest_is_denied(gateway, world, executor):
    result = await gateway.invoke(_ctx(world, "admin"), "ghost", "content.search", {})

    assert result.outcome == "denied_permission"
    assert executor.calls == []


# --- step 2: role permission -----------------------------------------------------------------


async def test_role_missing_from_allowed_roles_is_denied(gateway, world, executor):
    # The tutor manifest lists graph.prerequisites, but mcp-tools.md allows only student/faculty.
    result = await gateway.invoke(_ctx(world, "admin"), "tutor", "graph.prerequisites", {})

    assert result.outcome == "denied_permission"
    assert "admin" in result.guardrail["reason"]
    assert executor.calls == []


@pytest.mark.parametrize("person", ["student", "advisor"])
@pytest.mark.parametrize("tool, args", [
    ("content.save_draft", {"node_id": "c1", "kind": "skill", "title": "t", "body_md": "b"}),
    ("content.save_draft", {"kind": "summary", "title": "t", "body_md": "b"}),
    ("content.save_skill", {"concept_id": "c1", "body_md": "b"}),
])
async def test_shared_content_writes_refuse_students_and_advisors(gateway, world, executor,
                                                                  person, tool, args):
    result = await gateway.invoke(_ctx(world, person), "content_generator", tool,
                                  {**args, "author_id": world.people[person].id})

    assert result.outcome == "denied_permission"
    assert executor.calls == []


async def test_no_signed_in_requester_denies_everything(gateway, executor):
    result = await gateway.invoke(GatewayContext(auth=None), "tutor", "content.search", {})

    assert result.outcome == "denied_permission"
    assert executor.calls == []


async def test_student_role_cannot_commit_a_grade_through_any_agent(gateway, world, executor):
    student = _ctx(world, "student")

    via_grader = await gateway.invoke(student, "grading_assistant", "assessments.commit_grade",
                                      {"submission_id": "s", "score": 100})
    via_tutor = await gateway.invoke(student, "tutor", "assessments.commit_grade",
                                     {"submission_id": "s", "score": 100})

    assert via_grader.outcome == via_tutor.outcome == "denied_permission"
    assert executor.calls == []


# --- step 3: identity and scope --------------------------------------------------------------


async def test_student_identity_args_are_forced_to_self(gateway, world, executor):
    emma = world.people["student"]

    result = await gateway.invoke(
        _ctx(world, "student"), "tutor", "roster.get_student_context",
        {"person_id": "", "course_id": CS101.course_id},
    )

    assert result.outcome == "ok"
    assert executor.calls == [("roster.get_student_context",
                               {"person_id": emma.id, "course_id": CS101.course_id,
                                "requester_id": emma.id})]


async def test_student_gets_self_when_the_contract_declares_an_omitted_subject_id(
    gateway, world, executor,
):
    emma = world.people["student"]

    await gateway.invoke(_ctx(world, "student"), "tutor", "graph.prerequisites",
                         {"node_id": "n1"})

    assert executor.calls == [("graph.prerequisites", {"node_id": "n1", "person_id": emma.id})]


async def test_staff_omitted_subject_id_is_left_out(gateway, world, executor):
    await gateway.invoke(_ctx(world, "faculty"), "tutor", "graph.prerequisites",
                         {"node_id": "n1"})

    assert executor.calls == [("graph.prerequisites", {"node_id": "n1"})]


def test_input_keys_are_parsed_from_the_contract():
    roles = get_tool_roles()
    assert {"node_id", "person_id"} <= roles["graph.prerequisites"].input_keys
    assert "person_id" not in roles["content.search"].input_keys


def test_student_context_takes_the_caller_as_requester():
    assert "requester_id" in get_tool_roles()["roster.get_student_context"].input_keys


async def test_requester_id_is_always_the_caller(gateway, world, executor):
    torres = world.people["faculty"]
    noah = world.people["noah"]

    await gateway.invoke(_ctx(world, "faculty"), "tutor", "content.search",
                         {"query": "x", "requester_id": noah.id})

    assert executor.calls[0][1]["requester_id"] == torres.id


async def test_graded_by_is_always_the_caller(gateway, world, executor):
    torres = world.people["faculty"]
    noah = world.people["noah"]

    await gateway.invoke(_ctx(world, "faculty"), "tutor", "content.search",
                         {"query": "x", "graded_by": noah.id})

    assert executor.calls[0][1]["graded_by"] == torres.id


async def test_student_naming_another_learner_is_a_scope_denial(gateway, world, executor):
    noah = world.people["noah"]

    result = await gateway.invoke(_ctx(world, "student"), "tutor", "graph.mastery_map",
                                  {"person_id": noah.id})

    assert result.outcome == "denied_scope"
    assert result.guardrail["kind"] == "denied_scope"
    assert noah.id not in result.text and "Noah" not in result.guardrail["reason"]
    assert executor.calls == []


@pytest.mark.parametrize(("person", "subject", "allowed"), [
    ("faculty", "student", True),     # Torres teaches CS 101, Emma takes it
    ("faculty", "noah", False),       # Noah is only in ENG 102
    ("chen", "student", True),        # Chen teaches MATH 201, Emma takes it
    ("advisor", "student", True),     # Emma is Okafor's advisee
    ("advisor", "noah", False),
    ("admin", "noah", True),
])
async def test_staff_subject_ids_are_scope_checked(gateway, world, executor, person, subject,
                                                   allowed):
    role = "faculty" if person == "chen" else person
    agent = {"faculty": "early_alert", "advisor": "advising", "admin": "early_alert"}[role]
    student_id = world.people[subject].id

    result = await gateway.invoke(_ctx(world, person, role), agent, "roster.get_student_context",
                                  {"person_id": student_id})

    assert (result.outcome == "ok") is allowed
    assert (result.outcome == "denied_scope") is not allowed
    assert bool(executor.calls) is allowed


async def test_faculty_course_argument_narrows_scope(gateway, world, executor):
    emma = world.people["student"]

    result = await gateway.invoke(
        _ctx(world, "chen", "faculty"), "early_alert", "roster.get_student_context",
        {"person_id": emma.id, "course_id": CS101.course_id},
    )

    assert result.outcome == "denied_scope"
    assert MATH201.course_id != CS101.course_id


async def test_staff_scope_fails_closed_without_a_directory(world, executor):
    gateway = ToolGateway(executor)

    result = await gateway.invoke(_ctx(world, "faculty"), "early_alert",
                                  "roster.get_student_context",
                                  {"person_id": world.people["student"].id})

    assert result.outcome == "denied_scope"
    assert executor.calls == []


async def test_staff_own_id_needs_no_directory(world, executor):
    gateway = ToolGateway(executor)
    torres = world.people["faculty"]

    result = await gateway.invoke(_ctx(world, "faculty"), "tutor", "roster.get_goals",
                                  {"person_id": torres.id})

    assert result.outcome == "ok"


# --- step 7: execute -------------------------------------------------------------------------


async def test_server_error_text_is_an_error_outcome(world, turns):
    gateway = ToolGateway(RecordingExecutor('{"error": "boom"}'), directory=world.directory,
                          turns=turns)

    result = await gateway.invoke(_ctx(world, "student"), "tutor", "content.search",
                                  {"query": "x"})

    assert result.outcome == "error"
    assert result.success is False
    assert turns.rows[0].outcome == "error"


async def test_executor_exception_is_recorded_then_raised(world, turns):
    async def explode(tool: str, args: dict[str, Any]) -> str:
        raise RuntimeError("transport failed")

    gateway = ToolGateway(explode, directory=world.directory, turns=turns)

    with pytest.raises(RuntimeError):
        await gateway.invoke(_ctx(world, "student"), "tutor", "content.search", {})
    assert turns.rows[0].outcome == "error"


# --- step 10: provenance ---------------------------------------------------------------------


async def test_provenance_row_has_overwritten_redacted_args(gateway, world, turns):
    emma = world.people["student"]

    await gateway.invoke(_ctx(world, "student"), "tutor", "roster.get_student_context",
                         {"person_id": emma.id, "course_id": CS101.course_id,
                          "note": "reach me at emma@example.edu"})

    row = turns.rows[0]
    assert (row.turn_id, row.agent, row.tool, row.outcome) == (
        "turn-1", "tutor", "roster.get_student_context", "ok",
    )
    assert row.args == {"person_id": emma.id, "course_id": CS101.course_id,
                        "requester_id": emma.id, "note": "reach me at [REDACTED]"}
    assert isinstance(row.latency_ms, int)


async def test_provenance_failure_is_logged_and_the_call_still_returns(
    world, executor, caplog: pytest.LogCaptureFixture,
):
    setup_logging()
    gateway = ToolGateway(executor, directory=world.directory,
                          turns=FakeTurnRepository(fail=True))

    with caplog.at_level(logging.INFO):
        result = await gateway.invoke(_ctx(world, "student"), "tutor", "content.search",
                                      {"query": "x"})

    assert result.outcome == "ok"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].msg["event"] == "tool_call_provenance_failed"


async def test_turn_without_a_row_is_logged_not_persisted(
    world, executor, caplog: pytest.LogCaptureFixture,
):
    setup_logging()
    turns = FakeTurnRepository(exists=False)
    gateway = ToolGateway(executor, directory=world.directory, turns=turns)

    with caplog.at_level(logging.INFO):
        await gateway.invoke(_ctx(world, "student"), "tutor", "content.search", {"query": "x"})

    records = [r.msg for r in caplog.records if isinstance(r.msg, dict)]
    provenance = next(m for m in records if m["event"] == "tool_call_provenance")
    assert provenance["persisted"] is False
    assert turns.rows == []


# --- runner and dispatch through the gateway -------------------------------------------------


def _usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=100, output_tokens=50)


def _tool_use(name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="tool_use", usage=_usage(),
                           content=[SimpleNamespace(type="tool_use", id="tu1", name=name,
                                                    input=args)])


def _final(text: str = "Done.") -> SimpleNamespace:
    return SimpleNamespace(stop_reason="end_turn", usage=_usage(),
                           content=[SimpleNamespace(type="text", text=text)])


class FakeAnthropic:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_injected() -> Any:
    yield
    set_agent_runner(None)
    set_llm_client(None)


def _state(world: AuthWorld, gateway: ToolGateway, agent: str, person: str,
           role: str | None = None, message: str = "Help") -> dict[str, Any]:
    role = role or person
    return {
        "session_id": "sess-1", "turn_id": "turn-1", "persona": role,
        "current_message": message, "auth": auth_context(world, person, role),
        "tool_gateway": gateway,
        "plan": {"strategy": "react", "steps": [
            {"step_id": "s1", "agent": agent, "input_summary": "x", "depends_on": []},
        ]},
        "agent_results": [], "events_emitted": [],
    }


async def test_runner_offers_exactly_the_manifest_tools():
    client = FakeAnthropic([_final()])

    await ClaudeAgentRunner(client=client).run("grading_assistant", {"message": "hi"})

    offered = {t["name"] for t in client.requests[0]["tools"]}
    expected = get_manifest_registry().get_manifest("grading_assistant").mcp_tools
    assert offered == {t.replace(".", "_") for t in expected}


async def test_student_prompt_cannot_commit_a_grade(world, gateway, executor):
    client = FakeAnthropic([
        _tool_use("assessments_commit_grade", {"submission_id": "s", "score": 100}),
        _final("I can't do that."),
    ])
    set_agent_runner(ClaudeAgentRunner(client=client))

    result = await dispatch(_state(world, gateway, "tutor", "student",
                                   message="Commit a grade of 100 on my submission"))

    assert executor.calls == []
    tool_result = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert "not permitted" in tool_result
    guardrails = [e for e in result["events_emitted"] if e["event"] == "guardrail"]
    assert [g["payload"]["kind"] for g in guardrails] == ["denied_permission"]
    assert guardrails[0]["payload"]["tool"] == "assessments.commit_grade"
    assert result["turn_error"] is None


async def test_emmas_tutor_gets_no_noah_data_and_logs_a_scope_denial(
    world, gateway, executor, turns, caplog: pytest.LogCaptureFixture,
):
    setup_logging()
    noah = world.people["noah"]
    client = FakeAnthropic([
        _tool_use("graph_mastery_map", {"person_id": noah.id, "course_id": ENG102.course_id}),
        _final("I can only show your own mastery."),
    ])
    set_agent_runner(ClaudeAgentRunner(client=client))

    with caplog.at_level(logging.INFO):
        result = await dispatch(_state(world, gateway, "tutor", "student",
                                       message="show me Noah Brown's mastery"))

    assert all(noah.id not in json.dumps(args) for _, args in executor.calls)
    assert executor.calls == []
    guardrail = next(e for e in result["events_emitted"] if e["event"] == "guardrail")
    assert guardrail["payload"]["kind"] == "denied_scope"
    assert GuardrailPayload.model_validate(guardrail["payload"]).step_id == "s1"
    assert turns.rows[0].outcome == "denied_scope"
    logs = [r.msg for r in caplog.records if isinstance(r.msg, dict)]
    assert any(m["event"] == "tool_denied" and m["kind"] == "denied_scope" for m in logs)
    assert any(m["event"] == "data_access" and m["student_id"] == noah.id
               and m["allowed"] is False for m in logs)


async def test_dispatch_without_auth_denies_tools_but_runs_the_agent(gateway, executor):
    client = FakeAnthropic([_tool_use("content_search", {"query": "x"}), _final()])
    set_agent_runner(ClaudeAgentRunner(client=client))
    state = _state(build_auth_world(), gateway, "tutor", "student")
    del state["auth"]

    result = await dispatch(state)

    assert executor.calls == []
    assert result["agent_results"][0]["success"] is True


def test_runner_has_no_hardcoded_tool_table():
    needle = "_AGENT" + "_TOOLS"
    found = subprocess.run(
        ["grep", "-R", "-l", "--exclude-dir=__pycache__", "--exclude-dir=node_modules",
         "--exclude-dir=.next", needle, str(REPO_ROOT / "src")],
        capture_output=True, text=True,
    )
    assert found.returncode == 1, found.stdout


# --- persona routing with the real manifests -------------------------------------------------


@pytest.mark.parametrize("role", ["student", "faculty", "advisor", "admin", "program_lead"])
def test_each_persona_can_route_to_its_agents(role: str):
    matrix = get_permission_matrix()
    routable = matrix.allowed_agents(role) & ROUTABLE_AGENTS
    assert routable
    assert all(matrix.check_agent(role, a).allowed for a in routable)


def test_program_lead_reaches_program_agents():
    allowed = get_permission_matrix().allowed_agents("program_lead") & ROUTABLE_AGENTS
    assert {"engagement_analyst", "early_alert", "course_architect"} <= allowed


class TutorIntent:
    async def create_message(self, model, system, messages, max_tokens):  # noqa: ANN001
        return json.dumps({"action": "explain", "agent": "tutor", "parameters": {},
                           "confidence": 0.95})


async def test_program_lead_turn_falls_back_to_an_allowed_agent(monkeypatch: pytest.MonkeyPatch):
    async def no_mcp(tool: str, args: dict[str, Any]) -> str:
        return json.dumps({"turns": []})

    monkeypatch.setattr(runner_mod, "_call_mcp_tool", no_mcp)
    set_llm_client(TutorIntent())
    runner = StubAgentRunner()
    set_agent_runner(runner)
    world = build_auth_world()
    app = create_app(auth_service=world.service, scope_directory=world.directory)
    lead = world.people["program_lead"]
    session = Session(persona="program_lead", person_id=lead.id, course_id=CS101.course_id,
                      requester_name=lead.display_name)
    await app.state.session_store.create(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/auth/login",
                                  json={"username": lead.email, "password": DEMO_PASSWORD})
        assert login.status_code == 200
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        switched = await client.post("/api/auth/role", json={"role": "program_lead"})
        assert switched.status_code == 200
        resp = await client.post("/api/converse",
                                 json={"session_id": session.id, "message": "How are we doing?"})
        assert resp.status_code == 202
        turn: Turn | None = None
        for _ in range(200):
            turn = await app.state.turn_store.get(resp.json()["turn_id"])
            if turn is not None and turn.status in ("completed", "error"):
                break
            await asyncio.sleep(0.01)

    # The classifier picked tutor, which program_lead can't use; the turn runs the
    # persona's default agent instead of failing.
    assert turn is not None and turn.status == "completed"
    assert [call["agent"] for call in runner.calls] == ["engagement_analyst"]
    assert all(e["event"] != "error" for e in turn.events)


# --- step 3: course scope and actor ids -----------------------------------------------------


async def test_dr_chen_cannot_have_an_agent_read_the_cs101_roster(gateway, world, executor,
                                                                  turns):
    result = await gateway.invoke(_ctx(world, "chen", "faculty"), "early_alert",
                                  "roster.list_by_course", {"course_id": CS101.course_id})
    assert result.outcome == "denied_scope"
    assert result.guardrail is not None and result.guardrail["kind"] == "denied_scope"
    assert executor.calls == []
    assert turns.rows[-1].outcome == "denied_scope"


async def test_dr_chen_can_have_an_agent_read_the_math201_roster(gateway, world, executor):
    result = await gateway.invoke(_ctx(world, "chen", "faculty"), "early_alert",
                                  "roster.list_by_course", {"course_id": MATH201.course_id})
    assert result.outcome == "ok"
    assert executor.calls == [("roster.list_by_course", {"course_id": MATH201.course_id})]


async def test_a_course_slug_is_resolved_before_the_scope_check(gateway, world, executor):
    result = await gateway.invoke(_ctx(world, "chen", "faculty"), "early_alert",
                                  "roster.list_by_course", {"course_id": MATH201.slug})
    assert result.outcome == "ok"


async def test_analytics_scope_course_is_checked(gateway, world, executor):
    result = await gateway.invoke(
        _ctx(world, "chen", "faculty"), "early_alert", "analytics.query",
        {"metric": "avg_score", "scope": {"course_id": CS101.course_id}},
    )
    assert result.outcome == "denied_scope"
    assert executor.calls == []


async def test_analytics_scope_person_is_checked(gateway, world, executor):
    noah = world.people["noah"].id
    result = await gateway.invoke(
        _ctx(world, "chen", "faculty"), "early_alert", "analytics.query",
        {"metric": "avg_score", "scope": {"course_id": MATH201.course_id, "person_id": noah}},
    )
    assert result.outcome == "denied_scope"


@pytest.mark.parametrize("role", ["faculty", "student"])
async def test_all_courses_is_refused_outside_advisor_and_admin(gateway, world, executor, role):
    person = "chen" if role == "faculty" else "student"
    agent = "early_alert" if role == "faculty" else "tutor"
    tool = "roster.list_by_course" if role == "faculty" else "content.search"
    result = await gateway.invoke(_ctx(world, person, role), agent, tool, {"course_id": "all"})
    assert result.outcome == "denied_scope"
    assert executor.calls == []


async def test_admin_may_name_any_course(gateway, world, executor):
    result = await gateway.invoke(_ctx(world, "admin"), "early_alert",
                                  "roster.list_by_course", {"course_id": ENG102.course_id})
    assert result.outcome == "ok"


async def test_author_id_is_always_the_caller(gateway, world, executor):
    torres = world.people["faculty"].id
    await gateway.invoke(_ctx(world, "faculty"), "course_architect", "content.save_draft",
                         {"kind": "note", "title": "t", "body_md": "b",
                          "author_id": world.people["chen"].id})
    assert executor.calls[-1][1]["author_id"] == torres


async def test_a_students_attestation_carries_no_issuer(gateway, world, executor):
    await gateway.invoke(_ctx(world, "student"), "tutor", "attestations.attest",
                         {"person_id": "", "node_id": "n", "level": "proficient",
                          "issuer_id": world.people["chen"].id})
    args = executor.calls[-1][1]
    assert "issuer_id" not in args
    assert args["person_id"] == world.people["student"].id


async def test_faculty_attestation_issuer_is_the_caller(gateway, world, executor):
    chen = world.people["chen"].id
    await gateway.invoke(_ctx(world, "chen", "faculty"), "tutor", "attestations.attest",
                         {"person_id": world.people["student"].id, "node_id": "n",
                          "level": "proficient", "issuer_id": world.people["faculty"].id})
    assert executor.calls[-1][1]["issuer_id"] == chen


async def test_live_sink_gets_agent_start_first_and_each_tool_event_once(world, gateway, executor):
    client = FakeAnthropic([
        _tool_use("assessments_commit_grade", {"submission_id": "s", "score": 100}),
        _final("I can't do that."),
    ])
    set_agent_runner(ClaudeAgentRunner(client=client))
    live: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        live.append(event)

    state = _state(world, gateway, "tutor", "student", message="Commit a grade of 100")
    result = await dispatch({**state, "event_sink": sink})

    everything = live + result["events_emitted"]
    assert [e["event"] for e in live] == ["agent_start", "agent_tool_call", "guardrail"]
    assert sum(e["event"] == "agent_tool_call" for e in everything) == 1
    assert sum(e["event"] == "guardrail" for e in everything) == 1
    assert live[2]["payload"]["step_id"] == "s1"
