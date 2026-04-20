"""Tests for error handling and error event emission."""

from __future__ import annotations

import pytest

from engine.errors import (
    AgentError,
    BudgetExceededError,
    EngineError,
    LLMError,
    MCPError,
    PermissionDeniedError,
    TimeoutError,
    make_error_event,
)


def test_agent_error_event_payload():
    err = AgentError("tutor", "Connection refused", step_id="s1")
    payload = err.to_event_payload()
    assert payload["code"] == "agent_failure"
    assert "tutor" in payload["message"]
    assert payload["retriable"] is True
    assert payload["step_id"] == "s1"


def test_mcp_error_event_payload():
    err = MCPError("content.retrieve", "Timeout", step_id="s1")
    payload = err.to_event_payload()
    assert payload["code"] == "mcp_failure"
    assert "content.retrieve" in payload["message"]


def test_llm_error_event_payload():
    err = LLMError("Rate limited")
    payload = err.to_event_payload()
    assert payload["code"] == "llm_failure"
    assert "Rate limited" in payload["message"]
    assert payload["retriable"] is True


def test_budget_exceeded_error():
    err = BudgetExceededError("Token limit: 250000/250000")
    payload = err.to_event_payload()
    assert payload["code"] == "budget_exceeded"
    assert payload["retriable"] is False


def test_permission_denied_error():
    err = PermissionDeniedError("Students cannot send messages")
    payload = err.to_event_payload()
    assert payload["code"] == "permission_denied"
    assert payload["retriable"] is False


def test_timeout_error():
    err = TimeoutError("Wall time exceeded: 120000ms", step_id="s2")
    payload = err.to_event_payload()
    assert payload["code"] == "timeout"
    assert payload["step_id"] == "s2"


def test_make_error_event_from_engine_error():
    err = AgentError("tutor", "crashed")
    event = make_error_event(err)
    assert event["event"] == "error"
    assert event["payload"]["code"] == "agent_failure"


def test_make_error_event_from_generic_exception():
    err = ValueError("something went wrong internally")
    event = make_error_event(err)
    assert event["event"] == "error"
    assert event["payload"]["code"] == "internal"
    # Should NOT expose the raw error message
    assert "something went wrong internally" not in event["payload"]["message"]
    assert event["payload"]["retriable"] is True


def test_error_no_step_id():
    err = EngineError(code="internal", message="oops")
    payload = err.to_event_payload()
    assert "step_id" not in payload


def test_error_with_step_id():
    err = EngineError(code="internal", message="oops", step_id="s3")
    payload = err.to_event_payload()
    assert payload["step_id"] == "s3"
