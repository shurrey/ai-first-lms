"""Tests for POST /api/converse endpoint."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.models.session import Session


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_session(app) -> str:
    """Helper to create a session and return its id."""
    session = Session(persona="student", course_id="cs101")
    await app.state.session_store.create(session)
    return session.id


async def test_converse_returns_202(app, client):
    session_id = await _create_session(app)
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


async def test_converse_missing_message(app, client):
    session_id = await _create_session(app)
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
    })
    assert resp.status_code == 422


async def test_converse_creates_turn(app, client):
    session_id = await _create_session(app)
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


async def test_converse_stream_url_format(app, client):
    session_id = await _create_session(app)
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Test",
    })
    data = resp.json()
    assert data["stream_url"].startswith("/api/stream?")
    assert f"session_id={session_id}" in data["stream_url"]
    assert f"turn_id={data['turn_id']}" in data["stream_url"]
