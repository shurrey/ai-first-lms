from __future__ import annotations

import asyncio

import pytest

from engine.models.session import Session
from engine.tests.auth_fakes import CS101, ENG102, MATH201


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_tool(name, args):  # noqa: ANN001
        return "{}"

    async def no_brief(self, **kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr("engine.agents.runner._call_mcp_tool", fake_tool)
    monkeypatch.setattr("engine.brief.BriefGenerator.__init__", lambda self: None)
    monkeypatch.setattr("engine.brief.BriefGenerator.generate", no_brief)


async def _open(client, course_id: str, **extra):  # noqa: ANN001
    return await client.post("/api/session", json={"course_id": course_id, **extra})


async def test_create_session_returns_201_for_the_signed_in_person(authed_client, auth_world):
    client = await authed_client("student")
    resp = await _open(client, "cs101")
    assert resp.status_code == 201
    data = resp.json()
    assert data["person_id"] == auth_world.people["student"].id
    assert data["course_uuid"] == CS101.course_id
    assert data["brief_turn_id"] == f"brief-{data['session_id']}"


async def test_session_persona_is_the_active_role(authed_client, auth_app):
    client = await authed_client("program_lead")
    resp = await _open(client, CS101.course_id)
    assert resp.status_code == 201
    session = await auth_app.state.session_store.get(resp.json()["session_id"])
    assert session.persona == "program_lead"
    assert session.requester_name == "Dr. Maria Torres"


async def test_client_supplied_persona_and_person_id_are_ignored(authed_client, auth_world,
                                                                 auth_app):
    client = await authed_client("student")
    resp = await _open(client, "cs101", persona="admin", person_id=auth_world.people["noah"].id)
    assert resp.status_code == 201
    assert resp.json()["person_id"] == auth_world.people["student"].id
    session = await auth_app.state.session_store.get(resp.json()["session_id"])
    assert session.persona == "student"


@pytest.mark.parametrize(
    ("role", "person", "course", "status"),
    [
        ("student", None, "cs101", 201),
        ("student", None, MATH201.course_id, 201),
        ("student", None, "eng102", 403),
        ("student", None, "all", 403),
        ("faculty", None, "cs101", 201),
        ("faculty", None, "math201", 403),
        ("faculty", None, "all", 403),
        ("faculty", "chen", "math201", 201),
        ("faculty", "chen", "cs101", 403),
        ("advisor", None, "cs101", 201),
        ("advisor", None, "math201", 201),
        ("advisor", None, "eng102", 403),
        ("advisor", None, "all", 201),
        ("admin", None, "eng102", 201),
        ("admin", None, "all", 201),
        ("program_lead", None, "cs101", 201),
        ("program_lead", None, "eng102", 403),
        ("program_lead", None, "all", 403),
    ],
)
async def test_course_scope_per_role(authed_client, role, person, course, status):
    client = await authed_client(role, person=person)
    resp = await _open(client, course)
    assert resp.status_code == status, resp.text
    if status == 403:
        assert "detail" in resp.json()


async def test_program_lead_limited_to_program_courses_when_known(authed_client, auth_world):
    auth_world.directory.programs[auth_world.people["program_lead"].id] = frozenset(
        {CS101.course_id}
    )
    client = await authed_client("program_lead")
    assert (await _open(client, "cs101")).status_code == 201
    assert (await _open(client, "eng102")).status_code == 403


async def test_unknown_course_returns_404(authed_client):
    client = await authed_client("admin")
    assert (await _open(client, "nope999")).status_code == 404


async def test_create_session_requires_sign_in(auth_client):
    assert (await _open(auth_client, "cs101")).status_code == 401


async def test_create_session_missing_course_id(authed_client):
    client = await authed_client("student")
    resp = await client.post("/api/session", json={})
    assert resp.status_code == 422


async def test_admin_brief_counts_advisors_from_roles(authed_client, auth_world, monkeypatch):
    captured: dict = {}

    async def capture(self, **kwargs):  # noqa: ANN001
        captured.update(kwargs)

    monkeypatch.setattr("engine.brief.BriefGenerator.generate", capture)
    client = await authed_client("admin")
    assert (await _open(client, "all")).status_code == 201
    await _drain(client)
    assert captured["scope"].advisor_count == 1
    assert captured["scope"].course_ids is None


async def test_advisor_brief_is_limited_to_advisees(authed_client, auth_world, monkeypatch):
    captured: dict = {}

    async def capture(self, **kwargs):  # noqa: ANN001
        captured.update(kwargs)

    monkeypatch.setattr("engine.brief.BriefGenerator.generate", capture)
    client = await authed_client("advisor")
    assert (await _open(client, "all")).status_code == 201
    await _drain(client)
    scope = captured["scope"]
    assert scope.advisee_ids == {auth_world.people["student"].id}
    assert scope.course_ids == {CS101.course_id, MATH201.course_id}
    assert ENG102.course_id not in scope.course_ids


async def _drain(client) -> None:  # noqa: ANN001
    for _ in range(20):
        await asyncio.sleep(0)


async def test_session_store_persists(auth_app):
    store = auth_app.state.session_store
    session = Session(persona="student", course_id="cs101")
    await store.create(session)

    retrieved = await store.get(session.id)
    assert retrieved is not None
    assert retrieved.persona == "student"
    assert retrieved.course_id == "cs101"


async def test_session_store_get_missing(auth_app):
    assert await auth_app.state.session_store.get("nonexistent") is None
