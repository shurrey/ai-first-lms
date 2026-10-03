"""data_access_log writes from scope.can_view_student, via REST and the ToolGateway."""

from __future__ import annotations

import json
import logging
import sys
import types
from typing import Any

import pytest

from engine.app import create_app
from engine.auth.access_log import AccessEntry
from engine.auth.directory import SessionOwner
from engine.auth.scope import SensitiveRead, can_view_student
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.logging_config import setup_logging
from engine.tests.auth_fakes import CS101, ENG102, AuthWorld, auth_context
from engine.tests.object_fakes import InMemoryAccessLog, InMemoryObjectDirectory

EMMA_CS101_SESSION = "11111111-1111-4111-8111-111111111111"
NOAH_SESSION = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def access_log() -> InMemoryAccessLog:
    return InMemoryAccessLog()


@pytest.fixture
def auth_app(auth_world: AuthWorld, access_log: InMemoryAccessLog):
    """Overrides conftest's app so REST reads write to `access_log`."""
    return create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                      access_log=access_log)


@pytest.fixture(autouse=True)
def _sessions(auth_world: AuthWorld) -> None:
    d = auth_world.directory
    d.sessions[EMMA_CS101_SESSION] = SessionOwner(auth_world.people["student"].id,
                                                  CS101.course_id)
    d.sessions[NOAH_SESSION] = SessionOwner(auth_world.people["noah"].id, ENG102.course_id)


@pytest.fixture(autouse=True)
def fake_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(tool: str, args: dict[str, Any]) -> Any:
        return {"attributes": {"student_insights": []}} if tool == "roster.get" else {}

    monkeypatch.setattr("engine.agents.runner._call_mcp_json", fake)
    # engine.podcast creates /app/audio on import; the endpoint never reaches it here.
    podcast = types.ModuleType("engine.podcast")
    podcast.generate_podcast = None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "engine.podcast", podcast)


# --- can_view_student ----------------------------------------------------------------------


async def test_allowed_non_self_read_writes_one_row(auth_world, access_log):
    ctx = auth_context(auth_world, "faculty")
    emma = auth_world.people["student"].id

    allowed = await can_view_student(
        ctx, emma, CS101.course_id, purpose="faculty_roster_transcript",
        directory=auth_world.directory,
        read=SensitiveRead(access_log, "transcript", EMMA_CS101_SESSION))

    assert allowed
    assert access_log.entries == [AccessEntry(ctx.person_id, emma, "transcript",
                                              EMMA_CS101_SESSION, "faculty_roster_transcript")]


async def test_self_read_writes_no_row(auth_world, access_log):
    ctx = auth_context(auth_world, "student")

    assert await can_view_student(ctx, ctx.person_id, purpose="x",
                                  directory=auth_world.directory,
                                  read=SensitiveRead(access_log, "profile"))
    assert access_log.entries == []


async def test_denied_read_writes_no_row(auth_world, access_log):
    ctx = auth_context(auth_world, "faculty")
    noah = auth_world.people["noah"].id

    assert not await can_view_student(ctx, noah, purpose="x", directory=auth_world.directory,
                                      read=SensitiveRead(access_log, "profile"))
    assert access_log.entries == []


async def test_scope_check_without_a_sensitive_read_writes_no_row(auth_world, access_log):
    ctx = auth_context(auth_world, "admin")

    assert await can_view_student(ctx, auth_world.people["student"].id, purpose="mastery",
                                  directory=auth_world.directory)
    assert access_log.entries == []


async def test_failed_write_is_logged_and_the_read_still_allowed(auth_world, caplog):
    setup_logging()
    broken = InMemoryAccessLog(fail=True)
    ctx = auth_context(auth_world, "admin")

    with caplog.at_level(logging.ERROR):
        allowed = await can_view_student(ctx, auth_world.people["student"].id, purpose="x",
                                         directory=auth_world.directory,
                                         read=SensitiveRead(broken, "profile"))

    assert allowed
    errors = [r.msg for r in caplog.records if r.levelno == logging.ERROR
              and isinstance(r.msg, dict)]
    assert [e["event"] for e in errors] == ["data_access_log_write_failed"]


async def test_list_by_subject_is_newest_first(auth_world, access_log):
    emma = auth_world.people["student"].id
    for purpose in ("first", "second"):
        await can_view_student(auth_context(auth_world, "admin"), emma, purpose=purpose,
                               directory=auth_world.directory,
                               read=SensitiveRead(access_log, "profile"))

    rows = await access_log.list_by_subject(emma)

    assert [r.purpose for r in rows] == ["second", "first"]


# --- REST ------------------------------------------------------------------------------------


async def test_faculty_transcript_read_writes_one_row(authed_client, auth_world, access_log):
    client = await authed_client("faculty")

    resp = await client.get(f"/api/transcript/{EMMA_CS101_SESSION}")

    assert resp.status_code == 200
    assert access_log.entries == [AccessEntry(
        auth_world.people["faculty"].id, auth_world.people["student"].id, "transcript",
        EMMA_CS101_SESSION, "transcript")]


async def test_own_transcript_read_writes_no_row(authed_client, access_log):
    client = await authed_client("student")

    assert (await client.get(f"/api/transcript/{EMMA_CS101_SESSION}")).status_code == 200
    assert access_log.entries == []


async def test_denied_transcript_read_writes_no_row(authed_client, access_log):
    client = await authed_client("faculty")

    assert (await client.get(f"/api/transcript/{NOAH_SESSION}")).status_code == 403
    assert access_log.entries == []


async def test_advisor_insights_read_logs_an_analyst_summary(authed_client, auth_world,
                                                             access_log):
    client = await authed_client("advisor")
    emma = auth_world.people["student"].id

    assert (await client.get(f"/api/student-insights/{emma}")).status_code == 200
    assert [(e.resource, e.subject_id, e.purpose) for e in access_log.entries] == [
        ("analyst_summary", emma, "insights")]


async def test_own_insights_read_writes_no_row(authed_client, auth_world, access_log):
    client = await authed_client("student")

    resp = await client.get(f"/api/student-insights/{auth_world.people['student'].id}")

    assert resp.status_code == 200
    assert access_log.entries == []


async def test_faculty_goals_read_logs_a_profile_read(authed_client, auth_world, access_log):
    client = await authed_client("faculty")
    emma = auth_world.people["student"].id

    assert (await client.get(f"/api/student-goals/{emma}")).status_code == 200
    assert [(e.resource, e.subject_id, e.purpose) for e in access_log.entries] == [
        ("profile", emma, "goals")]


async def test_faculty_session_list_read_logs_a_transcript_read(authed_client, auth_world,
                                                                access_log):
    client = await authed_client("faculty")
    emma = auth_world.people["student"].id

    resp = await client.get(f"/api/student/{emma}/sessions", params={"course_id": CS101.course_id})

    assert resp.status_code == 200
    assert [(e.resource, e.subject_id, e.purpose) for e in access_log.entries] == [
        ("transcript", emma, "sessions")]


async def test_own_goals_and_sessions_reads_write_no_row(authed_client, auth_world,
                                                         access_log):
    client = await authed_client("student")
    emma = auth_world.people["student"].id

    assert (await client.get(f"/api/student-goals/{emma}")).status_code == 200
    assert (await client.get(f"/api/student/{emma}/sessions")).status_code == 200
    assert access_log.entries == []


# --- ToolGateway -----------------------------------------------------------------------------


class Mcp:
    def __init__(self, owners: dict[str, str]) -> None:
        self.owners = owners

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        if tool == "assessments.get_submission":
            owner = self.owners.get(args["submission_id"])
            return json.dumps({"id": args["submission_id"], "person_id": owner}
                              if owner else {"error": "Submission not found"})
        return json.dumps({"ok": True})


def _gateway(world: AuthWorld, log: InMemoryAccessLog) -> ToolGateway:
    emma, noah = world.people["student"].id, world.people["noah"].id
    owners = {"sub-emma": emma, "sub-noah": noah}
    objects = InMemoryObjectDirectory(submissions={"sub-emma": CS101.course_id,
                                                   "sub-noah": ENG102.course_id})
    return ToolGateway(Mcp(owners), directory=world.directory, objects=objects,
                       access_log=log)


def _ctx(world: AuthWorld, person: str, role: str | None = None) -> GatewayContext:
    return GatewayContext(auth=auth_context(world, person, role), session_id="sess-current",
                          turn_id="turn-1", step_id="s1", course_id=CS101.course_id)


@pytest.mark.parametrize("person, agent, tool, args, resource, resource_id", [
    ("faculty", "grading_assistant", "assessments.get_submission",
     {"submission_id": "sub-emma"}, "submission", "sub-emma"),
    ("admin", "grading_assistant", "assessments.get_submission",
     {"submission_id": "sub-emma"}, "submission", "sub-emma"),
    ("faculty", "learning_analyst", "roster.get_session_transcript",
     {"session_id": EMMA_CS101_SESSION}, "transcript", EMMA_CS101_SESSION),
    ("faculty", "learning_analyst", "roster.get_learner_profile",
     {"person_id": "<emma>"}, "profile", None),
    ("advisor", "advising", "roster.get_student", {"person_id": "<emma>"}, "profile", None),
    ("faculty", "tutor", "roster.get_goals", {"person_id": "<emma>"}, "profile", None),
    ("faculty", "learning_analyst", "roster.get_recent_turns",
     {"person_id": "<emma>", "course_id": CS101.course_id}, "transcript", None),
    ("faculty", "learning_analyst", "roster.list_student_sessions",
     {"person_id": "<emma>", "course_id": CS101.course_id}, "transcript", None),
])
async def test_gateway_sensitive_read_writes_one_row(auth_world, access_log, person, agent,
                                                     tool, args, resource, resource_id):
    emma = auth_world.people["student"].id
    args = {k: emma if v == "<emma>" else v for k, v in args.items()}

    result = await _gateway(auth_world, access_log).invoke(
        _ctx(auth_world, person), agent, tool, args)

    assert result.success, result.text
    assert access_log.entries == [AccessEntry(
        auth_world.people[person].id, emma, resource, resource_id, f"gateway:{agent}:{tool}")]


@pytest.mark.parametrize("agent, tool, args", [
    ("grading_assistant", "assessments.get_submission", {"submission_id": "sub-emma"}),
    ("learning_analyst", "roster.get_session_transcript", {"session_id": EMMA_CS101_SESSION}),
    ("learning_analyst", "roster.get_learner_profile", {"person_id": "<emma>"}),
])
async def test_gateway_self_read_writes_no_row(auth_world, access_log, agent, tool, args):
    emma = auth_world.people["student"].id
    args = {k: emma if v == "<emma>" else v for k, v in args.items()}

    result = await _gateway(auth_world, access_log).invoke(
        _ctx(auth_world, "student"), agent, tool, args)

    assert result.success, result.text
    assert access_log.entries == []


async def test_gateway_non_sensitive_read_writes_no_row(auth_world, access_log):
    result = await _gateway(auth_world, access_log).invoke(
        _ctx(auth_world, "faculty"), "tutor", "graph.mastery_map",
        {"person_id": auth_world.people["student"].id, "course_id": CS101.course_id})

    assert result.success, result.text
    assert access_log.entries == []


# --- object-level scope for submission_id / session_id ------------------------------------


@pytest.mark.parametrize("agent, tool, args", [
    ("grading_assistant", "assessments.get_submission", {"submission_id": "sub-noah"}),
    ("learning_analyst", "roster.get_session_transcript", {"session_id": NOAH_SESSION}),
])
async def test_faculty_of_another_course_is_denied_scope(auth_world, access_log, agent, tool,
                                                         args):
    result = await _gateway(auth_world, access_log).invoke(
        _ctx(auth_world, "faculty"), agent, tool, args)

    assert result.outcome == "denied_scope"
    assert result.guardrail is not None and result.guardrail["kind"] == "denied_scope"
    assert result.guardrail["tool"] == tool
    assert access_log.entries == []


async def test_podcast_audio_read_by_another_logs_a_profile_read(
        authed_client, auth_world, access_log, tmp_path, monkeypatch):
    import engine.api.podcast as podcast_api

    monkeypatch.setattr(podcast_api, "AUDIO_DIR", tmp_path)
    emma = auth_world.people["student"].id
    (tmp_path / "pod1.txt").write_text("HOST: hi")
    podcast_api.record_owner("pod1", emma)

    assert (await (await authed_client("student")).get("/audio/pod1.txt")).status_code == 200
    assert access_log.entries == []
    assert (await (await authed_client("advisor")).get("/audio/pod1.txt")).status_code == 200
    assert [(e.resource, e.subject_id, e.purpose) for e in access_log.entries] == [
        ("profile", emma, "podcast_audio")]


# --- GET /api/access-log (admin) -------------------------------------------------------------


def _log_reads(auth_world: AuthWorld, access_log: InMemoryAccessLog) -> tuple[str, str]:
    emma, faculty = auth_world.people["student"].id, auth_world.people["faculty"].id
    access_log.names[faculty] = "Dr. Torres"
    access_log.entries += [
        AccessEntry(faculty, emma, "transcript", EMMA_CS101_SESSION, "transcript"),
        AccessEntry(faculty, emma, "profile", None, "goals"),
        AccessEntry(faculty, auth_world.people["noah"].id, "profile", None, "goals"),
        AccessEntry(faculty, emma, "submission", None, "submission"),
    ]
    return emma, faculty


async def test_admin_reads_a_learners_access_log_newest_first(authed_client, auth_world,
                                                               access_log):
    emma, faculty = _log_reads(auth_world, access_log)
    client = await authed_client("admin")
    before = len(access_log.entries)

    resp = await client.get("/api/access-log", params={"subject_id": emma})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [e["resource"] for e in body["entries"]] == ["submission", "profile", "transcript"]
    assert body["entries"][-1] == {
        "id": "0", "actor": {"id": faculty, "display_name": "Dr. Torres"}, "subject_id": emma,
        "resource": "transcript", "resource_id": EMMA_CS101_SESSION, "purpose": "transcript",
        "created_at": body["entries"][-1]["created_at"]}
    assert body["next_before"] is None
    assert len(access_log.entries) == before


async def test_access_log_filters_by_resource_and_pages_with_next_before(authed_client,
                                                                        auth_world, access_log):
    emma, _ = _log_reads(auth_world, access_log)
    client = await authed_client("admin")

    profile = await client.get("/api/access-log",
                               params={"subject_id": emma, "resource": "profile"})
    assert [e["purpose"] for e in profile.json()["entries"]] == ["goals"]

    first = (await client.get("/api/access-log",
                              params={"subject_id": emma, "limit": 2})).json()
    second = (await client.get("/api/access-log", params={
        "subject_id": emma, "limit": 2, "before": first["next_before"]})).json()
    assert [e["id"] for e in first["entries"]] == ["3", "1"]
    assert first["next_before"] is not None
    assert [e["id"] for e in second["entries"]] == ["0"]
    assert second["next_before"] is None


@pytest.mark.parametrize("params", [
    {"subject_id": "not-a-uuid"},
    {},
    {"subject_id": "0f6e2c4a-5b1d-4c7e-9a3f-2d8b6e1c4a70", "resource": "ai_actions"},
    {"subject_id": "0f6e2c4a-5b1d-4c7e-9a3f-2d8b6e1c4a70", "before": "garbage"},
    {"subject_id": "0f6e2c4a-5b1d-4c7e-9a3f-2d8b6e1c4a70", "limit": 0},
    {"subject_id": "0f6e2c4a-5b1d-4c7e-9a3f-2d8b6e1c4a70", "from": "yesterday"},
])
async def test_bad_access_log_queries_are_422(authed_client, params):
    client = await authed_client("admin")
    assert (await client.get("/api/access-log", params=params)).status_code == 422


@pytest.mark.parametrize("role", ["student", "faculty", "advisor", "program_lead"])
async def test_only_admins_read_the_access_log(authed_client, auth_world, role):
    client = await authed_client(role)
    resp = await client.get("/api/access-log",
                            params={"subject_id": auth_world.people["student"].id})
    assert resp.status_code == 403
