"""Tests for GET /api/stream endpoint."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.models.session import Session
from engine.models.turn import Turn


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _setup_session_and_turn(app, status="completed"):
    """Create a session and turn with some events."""
    session = Session(persona="student", course_id="cs101")
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


async def test_stream_returns_sse(app, client):
    session_id, turn_id = await _setup_session_and_turn(app)
    resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


async def test_stream_contains_events(app, client):
    session_id, turn_id = await _setup_session_and_turn(app)
    resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={turn_id}")
    body = resp.text
    assert "reasoning" in body
    assert "final" in body


async def test_stream_nonexistent_turn(app, client):
    session = Session(persona="student", course_id="cs101")
    await app.state.session_store.create(session)
    resp = await client.get(f"/api/stream?session_id={session.id}&turn_id=nonexistent")
    body = resp.text
    assert "error" in body


async def test_stream_since_sequence(app, client):
    session_id, turn_id = await _setup_session_and_turn(app)
    # since_sequence=0 means get all events from the start
    resp = await client.get(
        f"/api/stream?session_id={session_id}&turn_id={turn_id}&since_sequence=0"
    )
    assert resp.status_code == 200
    body = resp.text
    # Should get all events
    assert "reasoning" in body
    assert "final" in body
