"""Tests for GET /api/stream endpoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.models.session import Session
from engine.models.turn import Turn
from engine.tests.auth_fakes import DEMO_PASSWORD
from engine.tests.persistence_fakes import FakePersistence


@pytest.fixture
def app(auth_app):
    return auth_app


@pytest.fixture
async def client(authed_client):
    return await authed_client("student")


@pytest.fixture
def emma(auth_world) -> str:
    return auth_world.people["student"].id


async def _setup_session_and_turn(app, person_id, status="completed"):
    """Create a session owned by `person_id` and a turn with some events."""
    session = Session(persona="student", person_id=person_id, course_id="cs101")
    await app.state.session_store.create(session)

    turn = Turn(session_id=session.id, message="Test", status=status)
    await app.state.turn_store.create(turn)

    # Add some events
    events = [
        {"event": "reasoning", "payload": {"step": "interpret", "text": "Thinking..."}},
        {"event": "plan", "payload": {"strategy": "react", "steps": []}},
        {"event": "final", "payload": {"answer_markdown": "Done", "artifacts": [],
                                        "cost_usd": 0.01, "tokens": 500, "wall_time_ms": 200}},
    ]
    await app.state.turn_store.add_events(turn.id, events)

    return session.id, turn.id


async def test_stream_returns_sse(app, client, emma):
    session_id, turn_id = await _setup_session_and_turn(app, emma)
    resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


async def test_stream_contains_events(app, client, emma):
    session_id, turn_id = await _setup_session_and_turn(app, emma)
    resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    body = resp.text
    assert "reasoning" in body
    assert "final" in body


async def test_stream_nonexistent_turn(app, client, emma):
    session = Session(persona="student", person_id=emma, course_id="cs101")
    await app.state.session_store.create(session)
    resp = await client.get(f"/api/stream?session_id={session.id}&turn_id=nonexistent")
    body = resp.text
    assert "error" in body


async def test_stream_since_sequence(app, client, emma):
    session_id, turn_id = await _setup_session_and_turn(app, emma)
    # since_sequence=0 means get all events from the start
    resp = await client.get(
        f"/api/stream?session_id={session_id}&turn_id={turn_id}&since_sequence=0"
    )
    assert resp.status_code == 200
    body = resp.text
    # Should get all events
    assert "reasoning" in body
    assert "final" in body


async def test_stream_for_someone_elses_turn_is_403(app, client, auth_world):
    session_id, turn_id = await _setup_session_and_turn(app, auth_world.people["noah"].id)
    resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    assert resp.status_code == 403
    assert "detail" in resp.json()


async def test_stream_turn_from_another_session_is_403(app, client, auth_world, emma):
    own_session, _ = await _setup_session_and_turn(app, emma)
    _, other_turn = await _setup_session_and_turn(app, auth_world.people["noah"].id)
    resp = await client.get(f"/api/stream?session_id={own_session}&turn_id={other_turn}")
    assert resp.status_code == 403


async def test_stream_unknown_session_is_403(client):
    resp = await client.get("/api/stream?session_id=nope&turn_id=nope")
    assert resp.status_code == 403


async def test_stream_requires_sign_in(app, auth_client, emma):
    session_id, turn_id = await _setup_session_and_turn(app, emma)
    resp = await auth_client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    assert resp.status_code == 401


def _envelopes(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines()
            if line.startswith("data: ")]


@asynccontextmanager
async def _signed_in(app, auth_world, role: str = "student") -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        person = auth_world.people[role]
        resp = await client.post(
            "/api/auth/login", json={"username": person.email, "password": DEMO_PASSWORD})
        assert resp.status_code == 200, resp.text
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        yield client


async def test_reconnect_keeps_the_original_sequence_numbers(app, client, emma):
    session_id, turn_id = await _setup_session_and_turn(app, emma)
    url = f"/api/stream?session_id={session_id}&turn_id={turn_id}"

    full = _envelopes((await client.get(url)).text)
    tail = _envelopes((await client.get(url + "&since_sequence=1")).text)

    assert [e["sequence"] for e in full] == [1, 2, 3]
    assert tail == full[1:]


async def test_live_stream_continues_after_the_replayed_tail(app, client, emma):
    session_id, turn_id = await _setup_session_and_turn(app, emma, status="active")

    async def finish_later() -> None:
        await asyncio.sleep(0.25)
        await app.state.turn_store.add_events(turn_id, [{"event": "reasoning", "payload": {
            "step": "synthesize", "text": "late"}}])
        await app.state.turn_store.update_status(turn_id, "completed")

    finisher = asyncio.create_task(finish_later())
    resp = await client.get(
        f"/api/stream?session_id={session_id}&turn_id={turn_id}&since_sequence=2")
    await finisher

    assert [(e["sequence"], e["event"]) for e in _envelopes(resp.text)] == [
        (3, "final"), (4, "reasoning")]


async def test_reconnect_after_restart_replays_from_the_repository(auth_world, emma):
    repo = FakePersistence()
    before = create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                        persistence=repo)
    session_id, turn_id = await _setup_session_and_turn(before, emma)
    async with _signed_in(before, auth_world) as client:
        original = _envelopes((await client.get(
            f"/api/stream?session_id={session_id}&turn_id={turn_id}")).text)

    after = create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                       persistence=repo)
    async with _signed_in(after, auth_world) as client:
        resp = await client.get(
            f"/api/stream?session_id={session_id}&turn_id={turn_id}&since_sequence=1")

    assert resp.status_code == 200
    assert _envelopes(resp.text) == original[1:]


async def test_after_restart_another_persons_turn_is_still_403(auth_world):
    repo = FakePersistence()
    before = create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                        persistence=repo)
    session_id, turn_id = await _setup_session_and_turn(before, auth_world.people["noah"].id)

    after = create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                       persistence=repo)
    async with _signed_in(after, auth_world) as client:
        resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    assert resp.status_code == 403
