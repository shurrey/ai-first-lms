"""Tests for the write-gate approval guardrail."""

from __future__ import annotations

import pytest

from engine.guardrails.approval import ApprovalDecision, ApprovalGate


@pytest.fixture
def gate():
    return ApprovalGate()


def test_requires_approval_for_grading(gate):
    assert gate.requires_approval("grading_assistant") is True


def test_requires_approval_for_send_tool(gate):
    assert gate.requires_approval("communication", "messages.send") is True


def test_no_approval_for_tutor(gate):
    assert gate.requires_approval("tutor") is False


def test_no_approval_for_read_tool(gate):
    assert gate.requires_approval("tutor", "content.retrieve") is False


def test_create_and_approve(gate):
    req = gate.create_request(
        step_id="s1",
        agent="grading_assistant",
        action="Commit grades for 23 students",
        preview={"grades": [{"student": "Alice", "score": 85}]},
        artifact_type="rubric_grades",
        tool_name="grades.commit",
    )
    assert gate.pending_count == 1

    decision = ApprovalDecision(approval_id=req.approval_id, decision="approve")
    resolved = gate.resolve(decision)

    assert resolved is not None
    assert resolved.agent == "grading_assistant"
    assert gate.pending_count == 0


def test_reject_removes_pending(gate):
    req = gate.create_request(
        step_id="s1",
        agent="communication",
        action="Send announcement",
        preview={"message": "Hello class"},
        artifact_type="message",
    )

    decision = ApprovalDecision(approval_id=req.approval_id, decision="reject", note="Not now")
    resolved = gate.resolve(decision)

    assert resolved is not None
    assert gate.pending_count == 0


def test_edit_updates_arguments(gate):
    req = gate.create_request(
        step_id="s1",
        agent="communication",
        action="Send message",
        preview={"message": "Original text"},
        artifact_type="message",
        tool_name="messages.send",
        tool_arguments={"body": "Original text"},
    )

    edited = {"body": "Edited text"}
    decision = ApprovalDecision(
        approval_id=req.approval_id,
        decision="edit",
        edited_payload=edited,
    )
    resolved = gate.resolve(decision)

    assert resolved is not None
    assert resolved.tool_arguments == {"body": "Edited text"}


def test_resolve_unknown_id(gate):
    decision = ApprovalDecision(approval_id="nonexistent", decision="approve")
    resolved = gate.resolve(decision)
    assert resolved is None


def test_to_event_payload(gate):
    req = gate.create_request(
        step_id="s1",
        agent="grading_assistant",
        action="Commit grades",
        preview={"grades": []},
        artifact_type="rubric_grades",
    )

    payload = gate.to_event_payload(req)
    assert payload["approval_id"] == req.approval_id
    assert payload["step_id"] == "s1"
    assert payload["agent"] == "grading_assistant"
    assert payload["action"] == "Commit grades"
    assert payload["artifact_type"] == "rubric_grades"


def test_get_pending(gate):
    req = gate.create_request(
        step_id="s1", agent="assessment", action="Save quiz",
        preview={}, artifact_type="quiz",
    )
    assert gate.get_pending(req.approval_id) is not None
    assert gate.get_pending("nonexistent") is None
