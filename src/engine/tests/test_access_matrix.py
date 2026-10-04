"""§17 authorization matrix over the existing endpoints (spec.md §20 "Auth and scope").

Each actor is (active role, AuthWorld.people key). "own" targets a learner or course
inside the actor's scope (Emma in the actor's course); "other" targets Noah / ENG 102,
which is outside every non-admin actor's scope.
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import pytest

from engine.app import create_app
from engine.auth.directory import SessionOwner
from engine.auth.scope import can_view_student
from engine.tests.auth_fakes import CS101, ENG102, MATH201
from engine.tests.object_fakes import InMemoryAccessLog

ACTORS: dict[str, tuple[str, str]] = {
    "student": ("student", "student"),
    "faculty": ("faculty", "faculty"),
    "faculty_chen": ("faculty", "chen"),
    "program_lead": ("program_lead", "program_lead"),
    "advisor": ("advisor", "advisor"),
    "admin": ("admin", "admin"),
}

OWN_COURSE = {actor: CS101.course_id for actor in ACTORS} | {"faculty_chen": MATH201.course_id}

OK, NO = 200, 403

# endpoint -> actor -> (own, other)
LEARNER_MATRIX: dict[str, dict[str, tuple[int, int]]] = {
    "mastery": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                "program_lead": (OK, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "student_sessions": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                         "program_lead": (NO, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "student_courses": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                        "program_lead": (OK, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "student_insights": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                         "program_lead": (NO, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "student_goals": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                      "program_lead": (NO, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "transcript": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                   "program_lead": (NO, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "credentials": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                    "program_lead": (OK, NO), "advisor": (OK, NO), "admin": (OK, OK)},
    "podcast": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                "program_lead": (NO, NO), "advisor": (NO, NO), "admin": (NO, NO)},
}

_STAFF = {"student": (NO, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
          "program_lead": (NO, NO), "advisor": (NO, NO), "admin": (OK, OK)}
COURSE_MATRIX: dict[str, dict[str, tuple[int, int]]] = {
    "roster": _STAFF,
    "pending_credentials": _STAFF,
    "credential_evidence": _STAFF,
    "approve_credential": _STAFF,
    "reject_credential": _STAFF,
}

ADMIN_ONLY = ("settings_get", "settings_post", "access_log")
SUBJECT = "0f6e2c4a-5b1d-4c7e-9a3f-2d8b6e1c4a70"


@pytest.fixture
def auth_app(auth_world):
    """With an access log, so GET /api/access-log can answer."""
    return create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                      access_log=InMemoryAccessLog())


def _pending_id(course_id: str) -> str:
    return f"pending-{course_id}"


def _session_id(course_id: str) -> str:
    return f"persisted-{course_id}"


async def _call(client, endpoint: str, *, person: str, course: str, me: str):  # noqa: ANN001
    """Issue one request; `person` / `course` are the target, `me` the caller's id."""
    match endpoint:
        case "mastery":
            return await client.get(f"/api/mastery/{person}/{course}")
        case "student_sessions":
            return await client.get(f"/api/student/{person}/sessions")
        case "student_courses":
            return await client.get(f"/api/student/{person}/courses")
        case "student_insights":
            return await client.get(f"/api/student-insights/{person}")
        case "student_goals":
            return await client.get(f"/api/student-goals/{person}")
        case "transcript":
            return await client.get(f"/api/transcript/{_session_id(course)}")
        case "credentials":
            return await client.get(f"/api/credentials/{person}")
        case "podcast":
            return await client.post("/api/generate-podcast",
                                     json={"person_id": person, "course_id": course})
        case "roster":
            return await client.get(f"/api/roster/{course}")
        case "pending_credentials":
            return await client.get(f"/api/pending-credentials/{course}")
        case "credential_evidence":
            return await client.get(f"/api/credential-evidence/{_pending_id(course)}")
        case "approve_credential":
            return await client.post(f"/api/approve-credential/{_pending_id(course)}",
                                     json={"reviewer_id": me})
        case "reject_credential":
            return await client.post(f"/api/reject-credential/{_pending_id(course)}",
                                     json={"reviewer_id": me, "reason": "Not yet"})
        case "access_log":
            return await client.get("/api/access-log", params={"subject_id": SUBJECT})
        case "settings_get":
            return await client.get("/api/settings")
        case "settings_post":
            return await client.post("/api/settings", json={"key": "k", "value": 1})
    raise AssertionError(endpoint)


@pytest.fixture(autouse=True)
def fake_mcp(monkeypatch: pytest.MonkeyPatch, auth_world) -> list[tuple[str, dict]]:
    """Every proxied MCP call succeeds with an empty-ish payload; calls are recorded."""
    calls: list[tuple[str, dict]] = []
    emma = auth_world.people["student"].id

    async def fake(tool: str, args: dict[str, Any]) -> Any:
        calls.append((tool, args))
        if tool == "roster.list_student_sessions":
            return {"sessions": [
                {"session_id": "a", "course_id": CS101.course_id,
                 "created_at": "2026-09-01T00:00:00Z", "turn_count": 1},
                {"session_id": "b", "course_id": MATH201.course_id,
                 "created_at": "2026-09-02T00:00:00Z", "turn_count": 1},
            ]}
        if tool == "sis.catalog_search":
            return {"courses": [{"id": CS101.course_id, "title": "CS 101"},
                                {"id": MATH201.course_id, "title": "MATH 201"}]}
        if tool == "roster.list_by_course":
            return {"persons": [{"id": emma, "display_name": "Emma Smith"}]}
        return {}

    monkeypatch.setattr("engine.agents.runner._call_mcp_json", fake)
    # engine.podcast creates /app/audio on import; the endpoint never reaches it here.
    podcast = types.ModuleType("engine.podcast")
    podcast.generate_podcast = None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "engine.podcast", podcast)
    return calls


@pytest.fixture(autouse=True)
def _fixtures(auth_world) -> None:
    emma, noah = auth_world.people["student"].id, auth_world.people["noah"].id
    d = auth_world.directory
    for course in (CS101, MATH201):
        d.sessions[_session_id(course.course_id)] = SessionOwner(emma, course.course_id)
        d.pending[_pending_id(course.course_id)] = course.course_id
    d.sessions[_session_id(ENG102.course_id)] = SessionOwner(noah, ENG102.course_id)
    d.pending[_pending_id(ENG102.course_id)] = ENG102.course_id


def _cases(matrix: dict[str, dict[str, tuple[int, int]]]):
    for endpoint, row in matrix.items():
        for actor, (own, other) in row.items():
            yield pytest.param(endpoint, actor, "own", own, id=f"{endpoint}-{actor}-own")
            yield pytest.param(endpoint, actor, "other", other, id=f"{endpoint}-{actor}-other")


@pytest.mark.parametrize(("endpoint", "actor", "target", "expected"),
                         list(_cases(LEARNER_MATRIX)) + list(_cases(COURSE_MATRIX)))
async def test_access_matrix(authed_client, auth_world, endpoint, actor, target, expected):
    role, person_key = ACTORS[actor]
    client = await authed_client(role, person=person_key)
    if target == "own":
        person, course = auth_world.people["student"].id, OWN_COURSE[actor]
    else:
        person, course = auth_world.people["noah"].id, ENG102.course_id
    resp = await _call(client, endpoint, person=person, course=course,
                       me=auth_world.people[person_key].id)
    assert resp.status_code == expected, resp.text
    if expected == NO:
        assert "detail" in resp.json()


@pytest.mark.parametrize("endpoint", ADMIN_ONLY)
@pytest.mark.parametrize("actor", list(ACTORS))
async def test_settings_admin_only(authed_client, auth_world, endpoint, actor):
    role, person_key = ACTORS[actor]
    client = await authed_client(role, person=person_key)
    resp = await _call(client, endpoint, person="", course="", me="")
    assert resp.status_code == (OK if actor == "admin" else NO)


ALL_ENDPOINTS = [*LEARNER_MATRIX, *COURSE_MATRIX, *ADMIN_ONLY]


@pytest.mark.parametrize("endpoint", ALL_ENDPOINTS)
async def test_every_endpoint_requires_sign_in(auth_client, auth_world, endpoint):
    resp = await _call(auth_client, endpoint, person=auth_world.people["student"].id,
                       course=CS101.course_id, me=auth_world.people["faculty"].id)
    assert resp.status_code == 401


async def test_audio_requires_sign_in(auth_client):
    assert (await auth_client.get("/audio/x.mp3")).status_code == 401


async def test_audio_rejects_path_like_names(authed_client):
    client = await authed_client("student")
    resp = await client.get("/audio/.hidden")
    assert resp.json() == {"error": "Audio file not found"}


@pytest.fixture
def audio_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001
    import engine.api.podcast as podcast_api

    monkeypatch.setattr(podcast_api, "AUDIO_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize(("role", "person", "expected"), [
    ("student", "student", 200),
    ("student", "noah", 403),
    ("faculty", "faculty", 200),
    ("advisor", "advisor", 200),
])
async def test_audio_is_served_only_to_viewers_of_its_learner(authed_client, auth_world,
                                                              audio_dir, role, person,
                                                              expected):
    from engine.api.podcast import record_owner

    (audio_dir / "abc123.txt").write_text("HOST: hi")
    record_owner("abc123", auth_world.people["student"].id)
    client = await authed_client(role, person=person)
    assert (await client.get("/audio/abc123.txt")).status_code == expected


async def test_audio_without_an_owner_record_is_not_served(authed_client, audio_dir):
    (audio_dir / "legacy1.txt").write_text("HOST: hi")
    client = await authed_client("admin")
    assert (await client.get("/audio/legacy1.txt")).json() == {"error": "Audio file not found"}


async def test_owner_records_are_not_servable(authed_client, auth_world, audio_dir):
    from engine.api.podcast import record_owner

    record_owner("abc123", auth_world.people["student"].id)
    client = await authed_client("student")
    assert (await client.get("/audio/abc123.owner")).json() == {"error": "Audio file not found"}


# ---- page briefs (POST /api/session with `page`) ---------------------------------

PAGE_MATRIX: dict[str, dict[str, int]] = {
    "student": {"content": 201, "calendar": 201, "mastery": 201, "courses": 201,
                "gradebook": 201, "roster": NO, "analytics": NO},
    "program_lead": {"content": 201, "calendar": 201, "mastery": 201, "courses": 201,
                     "gradebook": NO, "roster": NO, "analytics": NO},
    "faculty": {"gradebook": 201, "roster": 201, "analytics": 201},
    "advisor": {"gradebook": 201, "roster": 201, "analytics": 201},
    "admin": {"gradebook": 201, "roster": 201, "analytics": 201},
}


@pytest.mark.parametrize(("actor", "page", "expected"), [
    pytest.param(actor, page, code, id=f"{actor}-{page}")
    for actor, row in PAGE_MATRIX.items() for page, code in row.items()
])
async def test_page_brief_per_role(authed_client, monkeypatch, actor, page, expected):
    async def no_brief(self, **kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr("engine.brief.BriefGenerator.__init__", lambda self: None)
    monkeypatch.setattr("engine.brief.BriefGenerator.generate", no_brief)
    role, person_key = ACTORS[actor]
    client = await authed_client(role, person=person_key)
    resp = await client.post("/api/session", json={"course_id": CS101.course_id, "page": page})
    assert resp.status_code == expected, resp.text


# ---- the §4.8 acceptance cases, spelled out ---------------------------------------


async def test_emma_cannot_list_noahs_sessions(authed_client, auth_world):
    client = await authed_client("student")
    resp = await client.get(f"/api/student/{auth_world.people['noah'].id}/sessions")
    assert resp.status_code == 403


async def test_dr_chen_cannot_read_the_cs101_roster(authed_client):
    client = await authed_client("faculty", person="chen")
    assert (await client.get(f"/api/roster/{CS101.course_id}")).status_code == 403
    assert (await client.get(f"/api/roster/{MATH201.course_id}")).status_code == 200


# ---- endpoint details --------------------------------------------------------------


async def test_faculty_see_only_sessions_in_courses_they_teach(authed_client, auth_world):
    client = await authed_client("faculty", person="chen")
    resp = await client.get(f"/api/student/{auth_world.people['student'].id}/sessions")
    assert [s["course_id"] for s in resp.json()["sessions"]] == [MATH201.course_id]


async def test_student_sees_all_own_sessions(authed_client, auth_world):
    client = await authed_client("student")
    resp = await client.get(f"/api/student/{auth_world.people['student'].id}/sessions")
    assert len(resp.json()["sessions"]) == 2


async def test_faculty_course_filter_outside_their_course_is_403(authed_client, auth_world):
    client = await authed_client("faculty", person="chen")
    emma = auth_world.people["student"].id
    resp = await client.get(f"/api/student/{emma}/sessions",
                            params={"course_id": CS101.course_id})
    assert resp.status_code == 403


async def test_faculty_cannot_view_mastery_in_a_course_they_do_not_teach(authed_client,
                                                                         auth_world):
    client = await authed_client("faculty", person="chen")
    emma = auth_world.people["student"].id
    assert (await client.get(f"/api/mastery/{emma}/{CS101.course_id}")).status_code == 403


async def test_transcript_of_a_live_in_memory_session_uses_its_owner(authed_client, auth_world,
                                                                    auth_app):
    from engine.models.session import Session

    noah_session = Session(persona="student", person_id=auth_world.people["noah"].id,
                           course_id=ENG102.course_id)
    await auth_app.state.session_store.create(noah_session)
    client = await authed_client("student")
    assert (await client.get(f"/api/transcript/{noah_session.id}")).status_code == 403


async def test_unknown_transcript_session_is_403(authed_client):
    client = await authed_client("admin")
    assert (await client.get("/api/transcript/does-not-exist")).status_code == 403


async def test_approve_with_someone_elses_reviewer_id_is_403(authed_client, auth_world):
    client = await authed_client("faculty")
    resp = await client.post(f"/api/approve-credential/{_pending_id(CS101.course_id)}",
                             json={"reviewer_id": auth_world.people["chen"].id})
    assert resp.status_code == 403


async def test_approve_passes_the_caller_as_reviewer(authed_client, auth_world, fake_mcp):
    me = auth_world.people["faculty"].id
    client = await authed_client("faculty")
    await client.post(f"/api/approve-credential/{_pending_id(CS101.course_id)}",
                      json={"reviewer_id": me})
    assert fake_mcp[-1] == ("assessments.approve_credential",
                            {"pending_id": _pending_id(CS101.course_id), "reviewer_id": me})


async def test_bulk_approve_reports_out_of_scope_ids_per_item(authed_client, auth_world,
                                                              fake_mcp):
    me = auth_world.people["faculty"].id
    client = await authed_client("faculty")
    own, other = _pending_id(CS101.course_id), _pending_id(ENG102.course_id)
    resp = await client.post("/api/approve-credentials/bulk",
                             json={"pending_ids": [own, other], "reviewer_id": me})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0] == {"pending_id": own}
    assert results[1]["pending_id"] == other and "error" in results[1]
    assert [c for c in fake_mcp if c[0] == "assessments.approve_credential"] == [
        ("assessments.approve_credential", {"pending_id": own, "reviewer_id": me})
    ]


async def test_bulk_approve_with_someone_elses_reviewer_id_is_403(authed_client, auth_world):
    client = await authed_client("admin")
    resp = await client.post("/api/approve-credentials/bulk",
                             json={"pending_ids": [], "reviewer_id": auth_world.people["chen"].id})
    assert resp.status_code == 403


async def test_podcast_rejects_someone_elses_session(authed_client, auth_world, auth_app):
    from engine.models.session import Session

    noah_session = Session(persona="student", person_id=auth_world.people["noah"].id,
                           course_id=ENG102.course_id)
    await auth_app.state.session_store.create(noah_session)
    client = await authed_client("student")
    resp = await client.post("/api/generate-podcast", json={
        "person_id": auth_world.people["student"].id, "course_id": CS101.course_id,
        "session_id": noah_session.id,
    })
    assert resp.status_code == 403


async def test_program_lead_courses_are_limited_to_taught_courses(authed_client, auth_world):
    client = await authed_client("program_lead")
    resp = await client.get(f"/api/student/{auth_world.people['student'].id}/courses")
    assert resp.status_code == 200
    assert [c["course_id"] for c in resp.json()["courses"]] == [CS101.course_id]


# ---- can_view_student ------------------------------------------------------------


async def _ctx(auth_world, key: str, role: str | None = None):  # noqa: ANN001
    from engine.auth.models import SessionRecord

    person = auth_world.people[key]
    record = SessionRecord("s", b"", person.id, role or person.roles[0], "c",
                           auth_world.clock.now, auth_world.clock.now,
                           auth_world.clock.now, None, None)
    ctx = await auth_world.service.load_context(record)
    assert ctx is not None
    return ctx


async def test_can_view_student_logs_purpose_and_decision(auth_world, caplog):
    ctx = await _ctx(auth_world, "student")
    noah = auth_world.people["noah"].id
    with caplog.at_level(logging.INFO, logger="engine.auth.scope"):
        allowed = await can_view_student(ctx, noah, purpose="sessions",
                                         directory=auth_world.directory)
    assert allowed is False
    # structlog hands the stdlib record its event dict as `msg`.
    (entry,) = [r.msg for r in caplog.records
                if isinstance(r.msg, dict) and r.msg.get("event") == "data_access"]
    assert entry["purpose"] == "sessions"
    assert entry["allowed"] is False
    assert entry["student_id"] == noah
    assert entry["requester_id"] == ctx.person_id


async def test_can_view_student_self_is_always_allowed(auth_world):
    ctx = await _ctx(auth_world, "noah")
    assert await can_view_student(ctx, ctx.person_id, CS101.course_id, purpose="x",
                                  directory=auth_world.directory)


async def test_program_lead_without_teaching_sees_no_individuals(auth_world):
    from dataclasses import replace

    ctx = await _ctx(auth_world, "program_lead", role="program_lead")
    ctx = replace(ctx, enrollments=())
    emma = auth_world.people["student"].id
    assert not await can_view_student(ctx, emma, purpose="x", directory=auth_world.directory)
