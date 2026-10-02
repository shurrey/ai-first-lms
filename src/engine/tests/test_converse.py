"""Tests for POST /api/converse endpoint."""

from __future__ import annotations

import asyncio

import pytest

from engine.models.session import Session


@pytest.fixture
def app(auth_app):
    return auth_app


@pytest.fixture
async def client(authed_client):
    return await authed_client("student")


@pytest.fixture
def emma(auth_world) -> str:
    return auth_world.people["student"].id


async def _create_session(app, person_id: str | None = None, persona: str = "student") -> str:
    session = Session(persona=persona, person_id=person_id, course_id="cs101")
    await app.state.session_store.create(session)
    return session.id


async def test_converse_returns_202(app, client, emma):
    session_id = await _create_session(app, emma)
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Help me understand recursion",
    })
    assert resp.status_code == 202
    data = resp.json()
    assert "turn_id" in data
    assert "stream_url" in data


async def test_converse_invalid_session(client):
    resp = await client.post("/api/converse", json={
        "session_id": "nonexistent",
        "message": "hello",
    })
    assert resp.status_code == 404


async def test_converse_missing_message(app, client, emma):
    session_id = await _create_session(app, emma)
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
    })
    assert resp.status_code == 422


async def test_converse_creates_turn(app, client, emma):
    session_id = await _create_session(app, emma)
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Test message",
    })
    turn_id = resp.json()["turn_id"]

    # Give the background task a moment to start
    await asyncio.sleep(0.1)

    turn = await app.state.turn_store.get(turn_id)
    assert turn is not None
    assert turn.session_id == session_id
    assert turn.message == "Test message"


async def test_converse_stream_url_format(app, client, emma):
    session_id = await _create_session(app, emma)
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Test",
    })
    data = resp.json()
    assert data["stream_url"].startswith("/api/stream?")
    assert f"session_id={session_id}" in data["stream_url"]
    assert f"turn_id={data['turn_id']}" in data["stream_url"]


async def test_converse_rejects_someone_elses_session(app, client, auth_world):
    session_id = await _create_session(app, auth_world.people["noah"].id)
    resp = await client.post("/api/converse", json={"session_id": session_id, "message": "hi"})
    assert resp.status_code == 403


async def test_converse_rejects_session_opened_under_another_role(app, authed_client, auth_world):
    client = await authed_client("program_lead")
    session_id = await _create_session(app, auth_world.people["faculty"].id, persona="faculty")
    resp = await client.post("/api/converse", json={"session_id": session_id, "message": "hi"})
    assert resp.status_code == 403


async def test_converse_requires_sign_in(app, auth_client, emma):
    session_id = await _create_session(app, emma)
    resp = await auth_client.post("/api/converse", json={"session_id": session_id, "message": "x"})
    assert resp.status_code == 401


async def test_the_turn_task_is_held_until_it_finishes(app, client, emma, monkeypatch):
    import engine.api.converse as converse_mod

    release = asyncio.Event()

    async def fake_run_graph(*_args):
        await release.wait()

    monkeypatch.setattr(converse_mod, "_run_graph", fake_run_graph)
    session_id = await _create_session(app, emma)
    resp = await client.post("/api/converse", json={"session_id": session_id, "message": "x"})
    turn_id = resp.json()["turn_id"]

    held = [t for t in app.state.background_tasks if t.get_name() == f"turn-{turn_id}"]
    assert len(held) == 1
    release.set()
    await held[0]
    await asyncio.sleep(0)
    assert held[0] not in app.state.background_tasks


async def test_a_failed_background_task_is_logged_and_released(caplog):
    from engine.background import spawn

    async def boom():
        raise RuntimeError("kaput")

    tasks: set[asyncio.Task] = set()
    with caplog.at_level("ERROR", logger="engine.background"):
        task = spawn(tasks, boom(), name="turn-x")
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    assert tasks == set()
    assert "turn-x" in caplog.text and "kaput" in caplog.text
