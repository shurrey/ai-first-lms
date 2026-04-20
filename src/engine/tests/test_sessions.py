from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_create_session_returns_201(client):
    resp = await client.post("/api/session", json={
        "persona": "student",
        "course_id": "cs101",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    assert isinstance(data["session_id"], str)


async def test_create_session_with_person_id(client):
    resp = await client.post("/api/session", json={
        "persona": "faculty",
        "person_id": "person-123",
        "course_id": "cs101",
    })
    assert resp.status_code == 201


async def test_create_session_invalid_persona(client):
    resp = await client.post("/api/session", json={
        "persona": "hacker",
        "course_id": "cs101",
    })
    assert resp.status_code == 422


async def test_create_session_missing_course_id(client):
    resp = await client.post("/api/session", json={
        "persona": "student",
    })
    assert resp.status_code == 422


async def test_session_store_persists(app):
    store = app.state.session_store
    from engine.models.session import Session

    session = Session(persona="student", course_id="cs101")
    await store.create(session)

    retrieved = await store.get(session.id)
    assert retrieved is not None
    assert retrieved.persona == "student"
    assert retrieved.course_id == "cs101"


async def test_session_store_get_missing(app):
    store = app.state.session_store
    result = await store.get("nonexistent")
    assert result is None
