"""Tests for POST /api/approval endpoint."""

from __future__ import annotations

import json

import pytest

import engine.agents.runner as runner_mod
from engine.app import create_app
from engine.models.session import Session
from engine.models.turn import Turn
from engine.tests.auth_fakes import CS101
from engine.tests.object_fakes import InMemoryObjectDirectory


@pytest.fixture
def auth_app(auth_world):
    objects = InMemoryObjectDirectory(submissions={"sub1": CS101.course_id,
                                                   "sub2": CS101.course_id})
    return create_app(auth_service=auth_world.service, scope_directory=auth_world.directory,
                      object_directory=objects)


@pytest.fixture
def app(auth_app, auth_world, monkeypatch):
    """Grade draft g1 is for a CS 101 submission by the demo student."""
    student_id = auth_world.people["student"].id

    async def fake_mcp(tool, args):
        if tool == "assessments.get_submission":
            return json.dumps({"id": args["submission_id"], "person_id": student_id})
        return json.dumps({"ok": True})

    monkeypatch.setattr(runner_mod, "_call_mcp_tool", fake_mcp)
    auth_app.state.tool_gateway.drafts.remember(
        "grade", "g1", auth_world.people["faculty"].id, {"submission_id": "sub1"})
    return auth_app


@pytest.fixture
async def client(authed_client):
    return await authed_client("faculty")


async def _own_turn(app, person_id: str, persona: str = "faculty") -> tuple[str, str]:
    session = Session(persona=persona, person_id=person_id, course_id=CS101.course_id)
    await app.state.session_store.create(session)
    turn = Turn(session_id=session.id, message="grade these")
    await app.state.turn_store.create(turn)
    return session.id, turn.id


@pytest.fixture
async def ids(app, auth_world) -> dict[str, str]:
    session_id, turn_id = await _own_turn(app, auth_world.people["faculty"].id)
    return {"session_id": session_id, "turn_id": turn_id}


def _create_pending_approval(app, turn_id: str = "", course_id: str = CS101.course_id) -> str:
    gate = app.state.approval_gate
    req = gate.create_request(
        step_id="s1",
        agent="grading_assistant",
        action="Commit grade",
        preview={"tool": "assessments.commit_grade", "arguments": {"grade_id": "g1"}},
        artifact_type="grade_commit",
        tool_name="assessments.commit_grade",
        tool_arguments={"grade_id": "g1"},
        turn_id=turn_id,
        course_id=course_id,
    )
    return req.approval_id


async def test_approve_returns_202(app, client, ids):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        **ids,
        "approval_id": approval_id,
        "decision": "approve",
    })
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["decision"] == "approve"


async def test_reject_returns_202(app, client, ids):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        **ids,
        "approval_id": approval_id,
        "decision": "reject",
        "note": "Not appropriate right now",
    })
    assert resp.status_code == 202
    assert resp.json()["decision"] == "reject"


async def test_edit_returns_202(app, client, ids):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        **ids,
        "approval_id": approval_id,
        "decision": "edit",
        "edited_payload": {"grade_id": "g1"},
    })
    assert resp.status_code == 202
    assert resp.json()["decision"] == "edit"


@pytest.mark.parametrize("edited", [
    {"grade_id": "g2"},
    {},
    {"grade_id": "g1", "person_id": "someone"},
])
async def test_an_edit_that_changes_what_is_acted_on_is_422(app, client, ids, edited):
    app.state.tool_gateway.drafts.remember("grade", "g2", "x", {"submission_id": "sub2"})
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        **ids, "approval_id": approval_id, "decision": "edit", "edited_payload": edited,
    })

    assert resp.status_code == 422
    assert app.state.approval_gate.get_pending(approval_id) is not None


async def test_an_edit_adding_an_undeclared_key_is_422(app, client, ids):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        **ids, "approval_id": approval_id, "decision": "edit",
        "edited_payload": {"grade_id": "g1", "force": True},
    })

    assert resp.status_code == 422


async def test_unknown_approval_returns_404(client, ids):
    resp = await client.post("/api/approval", json={
        **ids,
        "approval_id": "nonexistent",
        "decision": "approve",
    })
    assert resp.status_code == 404


async def test_invalid_decision_returns_422(app, client, ids):
    approval_id = _create_pending_approval(app)
    resp = await client.post("/api/approval", json={
        **ids,
        "approval_id": approval_id,
        "decision": "invalid_decision",
    })
    assert resp.status_code == 422


async def test_double_resolve_returns_404(app, client, ids):
    approval_id = _create_pending_approval(app)
    # First resolve
    resp1 = await client.post("/api/approval", json={
        **ids,
        "approval_id": approval_id,
        "decision": "approve",
    })
    assert resp1.status_code == 202

    # Second resolve should fail (already resolved)
    resp2 = await client.post("/api/approval", json={
        **ids,
        "approval_id": approval_id,
        "decision": "approve",
    })
    assert resp2.status_code == 404


async def test_approval_for_someone_elses_session_is_403(app, client, auth_world):
    approval_id = _create_pending_approval(app)
    session_id, turn_id = await _own_turn(app, auth_world.people["chen"].id)
    resp = await client.post("/api/approval", json={
        "session_id": session_id, "turn_id": turn_id,
        "approval_id": approval_id, "decision": "approve",
    })
    assert resp.status_code == 403
    assert app.state.approval_gate.get_pending(approval_id) is not None


async def test_approval_with_turn_from_another_session_is_403(app, client, auth_world, ids):
    approval_id = _create_pending_approval(app)
    _, other_turn = await _own_turn(app, auth_world.people["chen"].id)
    resp = await client.post("/api/approval", json={
        "session_id": ids["session_id"], "turn_id": other_turn,
        "approval_id": approval_id, "decision": "approve",
    })
    assert resp.status_code == 403


async def test_approval_for_another_turn_is_404(app, client, ids):
    approval_id = _create_pending_approval(app, turn_id="some-other-turn")
    resp = await client.post("/api/approval", json={
        **ids, "approval_id": approval_id, "decision": "approve",
    })
    assert resp.status_code == 404


async def test_student_approver_is_403(app, authed_client, auth_world):
    student = await authed_client("student")
    session_id, turn_id = await _own_turn(app, auth_world.people["student"].id, "student")
    approval_id = _create_pending_approval(app, turn_id)

    resp = await student.post("/api/approval", json={
        "session_id": session_id, "turn_id": turn_id,
        "approval_id": approval_id, "decision": "approve",
    })

    assert resp.status_code == 403
    assert app.state.approval_gate.get_pending(approval_id) is not None


async def test_faculty_of_another_course_is_403(app, authed_client, auth_world):
    chen = await authed_client("faculty", person="chen")
    session_id, turn_id = await _own_turn(app, auth_world.people["chen"].id)
    approval_id = _create_pending_approval(app, turn_id, course_id=CS101.course_id)

    resp = await chen.post("/api/approval", json={
        "session_id": session_id, "turn_id": turn_id,
        "approval_id": approval_id, "decision": "approve",
    })

    assert resp.status_code == 403
    assert app.state.approval_gate.get_pending(approval_id) is not None


async def test_reject_needs_no_tool_permission(app, authed_client, auth_world):
    chen = await authed_client("faculty", person="chen")
    session_id, turn_id = await _own_turn(app, auth_world.people["chen"].id)
    approval_id = _create_pending_approval(app, turn_id)

    resp = await chen.post("/api/approval", json={
        "session_id": session_id, "turn_id": turn_id,
        "approval_id": approval_id, "decision": "reject",
    })

    assert resp.status_code == 202
