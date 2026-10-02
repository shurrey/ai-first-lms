"""Tests for the permission guardrail."""

from __future__ import annotations

import pytest

from engine.guardrails.permissions import PermissionMatrix
from engine.manifests import load_manifests


@pytest.fixture
def matrix():
    registry = load_manifests()
    return PermissionMatrix.from_registry(registry)


def test_student_can_use_tutor(matrix):
    check = matrix.check_agent("student", "tutor")
    assert check.allowed is True


def test_student_cannot_use_grading_assistant(matrix):
    check = matrix.check_agent("student", "grading_assistant")
    assert check.allowed is False
    assert "not allowed" in check.reason


def test_faculty_can_use_grading_assistant(matrix):
    check = matrix.check_agent("faculty", "grading_assistant")
    assert check.allowed is True


def test_student_cannot_access_communications_send_message(matrix):
    check = matrix.check_tool("student", "communications.send_message")
    assert check.allowed is False


def test_faculty_can_access_assessments_commit_grade(matrix):
    check = matrix.check_tool("faculty", "assessments.commit_grade")
    assert check.allowed is True


def test_student_can_access_content_tools(matrix):
    check = matrix.check_tool("student", "content.retrieve")
    assert check.allowed is True

    check = matrix.check_tool("student", "content.search")
    assert check.allowed is True


def test_advisor_can_use_early_alert(matrix):
    check = matrix.check_agent("advisor", "early_alert")
    assert check.allowed is True


def test_advisor_cannot_use_assessment(matrix):
    check = matrix.check_agent("advisor", "assessment")
    assert check.allowed is False


def test_unknown_persona_denied(matrix):
    check = matrix.check_agent("hacker", "tutor")
    assert check.allowed is False


def test_unknown_tool_denied(matrix):
    check = matrix.check_tool("student", "nonexistent.tool")
    assert check.allowed is False


def test_allowed_agents_returns_set(matrix):
    agents = matrix.allowed_agents("student")
    assert isinstance(agents, set)
    assert "tutor" in agents
    assert "grading_assistant" not in agents


def test_allowed_tools_returns_set(matrix):
    tools = matrix.allowed_tools("faculty")
    assert isinstance(tools, set)
    assert "assessments.commit_grade" in tools
