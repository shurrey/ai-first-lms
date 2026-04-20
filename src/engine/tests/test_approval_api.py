"""Tests for POST /api/approval endpoint."""

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


def _create_pending_approval(app) -> str:
    """Create a pending approval and return its ID."""
    gate = app.state.approval_gate
    req = gate.create_request(
        step_id="s1",
        agent="grading_assistant",
        action="Commit grades for 23 students",
        preview={"grades": [{"student": "Alice", "score": 85}]},
        artifact_type="rubric_grades",
        tool_name="grades.commit",
    )
    return req.approval_id


async def test_approve_returns_202(app, client):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": approval_id,
        "decision": "approve",
    })
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["decision"] == "approve"


async def test_reject_returns_202(app, client):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": approval_id,
        "decision": "reject",
        "note": "Not appropriate right now",
    })
    assert resp.status_code == 202
    assert resp.json()["decision"] == "reject"


async def test_edit_returns_202(app, client):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": approval_id,
        "decision": "edit",
        "edited_payload": {"grades": [{"student": "Alice", "score": 90}]},
    })
    assert resp.status_code == 202
    assert resp.json()["decision"] == "edit"


async def test_unknown_approval_returns_404(client):
    resp = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": "nonexistent",
        "decision": "approve",
    })
    assert resp.status_code == 404


async def test_invalid_decision_returns_422(app, client):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": approval_id,
        "decision": "invalid_decision",
    })
    assert resp.status_code == 422


async def test_double_resolve_returns_404(app, client):
    approval_id = _create_pending_approval(app)
    # First resolve
    resp1 = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": approval_id,
        "decision": "approve",
    })
    assert resp1.status_code == 202

    # Second resolve should fail (already resolved)
    resp2 = await client.post("/api/approval", json={
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": approval_id,
        "decision": "approve",
    })
    assert resp2.status_code == 404
