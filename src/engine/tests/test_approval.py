"""Tests for the write-gate approval guardrail."""

from __future__ import annotations

import asyncio

import pytest

from engine.guardrails.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalTimeoutError,
    artifact_type_for,
)
from engine.guardrails.tool_roles import load_tool_roles


@pytest.fixture
def gate():
    return ApprovalGate()


@pytest.mark.parametrize("tool", [
    "assessments.commit_grade",
    "assessments.approve_credential",
    "assessments.create_question",
    "communications.send_message",
])
def test_contract_marks_served_write_tools_as_requiring_approval(tool):
    assert load_tool_roles()[tool].requires_approval is True


@pytest.mark.parametrize("tool", ["assessments.draft_grade", "content.retrieve"])
def test_contract_leaves_other_tools_ungated(tool):
    assert load_tool_roles()[tool].requires_approval is False


def test_artifact_types_follow_the_events_contract():
    assert artifact_type_for("assessments.commit_grade") == "grade_commit"
    assert artifact_type_for("assessments.approve_credential") == "credential"
    assert artifact_type_for("assessments.create_question") == "quiz"
    assert artifact_type_for("communications.send_message") == "message"
    assert artifact_type_for("something.else") == "other"


async def test_wait_returns_the_resolution(gate):
    req = gate.create_request(step_id="s1", agent="grading_assistant", action="Commit grade",
                              preview={}, artifact_type="grade_commit",
                              tool_name="assessments.commit_grade",
                              tool_arguments={"grade_id": "g1"})
    waiter = asyncio.create_task(gate.wait(req.approval_id, timeout_s=5))
    await asyncio.sleep(0)
    gate.resolve(ApprovalDecision(req.approval_id, "edit", {"grade_id": "g2"}))

    resolution = await waiter
    assert resolution.decision.decision == "edit"
    assert resolution.tool_arguments == {"grade_id": "g2"}


async def test_a_decision_before_wait_is_not_lost(gate):
    req = gate.create_request(step_id="s1", agent="a", action="x", preview={},
                              artifact_type="other")
    gate.resolve(ApprovalDecision(req.approval_id, "reject"))

    resolution = await gate.wait(req.approval_id, timeout_s=1)
    assert resolution.decision.decision == "reject"


async def test_wait_times_out_and_drops_the_request(gate):
    req = gate.create_request(step_id="s1", agent="a", action="x", preview={},
                              artifact_type="other")
    with pytest.raises(ApprovalTimeoutError):
        await gate.wait(req.approval_id, timeout_s=0.01)
    assert gate.get_pending(req.approval_id) is None


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


def test_original_arguments_do_not_share_nested_values(gate):
    args = {"audience": {"person_ids": ["p1"]}}
    req = gate.create_request(step_id="s1", agent="a", action="x", preview={},
                              artifact_type="message", tool_arguments=args)

    args["audience"]["person_ids"].append("p2")
    req.tool_arguments["audience"]["person_ids"].append("p3")

    assert req.original_arguments == {"audience": {"person_ids": ["p1"]}}
