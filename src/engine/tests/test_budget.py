"""Tests for the budget guardrail."""

from __future__ import annotations

import pytest

from engine.guardrails.budget import BudgetConfig, BudgetTracker


def test_under_budget():
    config = BudgetConfig(
        max_tokens=100_000, max_tool_calls=40,
        max_wall_time_ms=120_000, max_agent_invocations=8,
    )
    tracker = BudgetTracker(config)
    tracker.charge(tokens=5000)
    tracker.charge(tool_calls=1)
    tracker.charge(agent_invocations=1)

    result = tracker.check()
    assert result.exceeded is False


def test_token_limit_exceeded():
    config = BudgetConfig(
        max_tokens=1000, max_tool_calls=100,
        max_wall_time_ms=120_000, max_agent_invocations=8,
    )
    tracker = BudgetTracker(config)
    tracker.charge(tokens=1500)

    result = tracker.check()
    assert result.exceeded is True
    assert "Token limit" in result.reason


def test_tool_call_limit_exceeded():
    config = BudgetConfig(
        max_tokens=100_000, max_tool_calls=2,
        max_wall_time_ms=120_000, max_agent_invocations=8,
    )
    tracker = BudgetTracker(config)
    tracker.charge(tool_calls=1)
    tracker.charge(tool_calls=1)
    tracker.charge(tool_calls=1)

    result = tracker.check()
    assert result.exceeded is True
    assert "Tool call limit" in result.reason


def test_agent_invocation_limit_exceeded():
    config = BudgetConfig(
        max_tokens=100_000, max_tool_calls=100,
        max_wall_time_ms=120_000, max_agent_invocations=2,
    )
    tracker = BudgetTracker(config)
    tracker.charge(agent_invocations=1)
    tracker.charge(agent_invocations=1)
    tracker.charge(agent_invocations=1)

    result = tracker.check()
    assert result.exceeded is True
    assert "Agent invocation limit" in result.reason


def test_wall_time_limit():
    config = BudgetConfig(
        max_tokens=100_000, max_tool_calls=100,
        max_wall_time_ms=1,  # 1ms — will be exceeded immediately
        max_agent_invocations=8,
    )
    tracker = BudgetTracker(config)
    import time
    time.sleep(0.01)  # 10ms

    result = tracker.check()
    assert result.exceeded is True
    assert "Wall time limit" in result.reason


def test_summary():
    config = BudgetConfig(
        max_tokens=100_000, max_tool_calls=100,
        max_wall_time_ms=120_000, max_agent_invocations=8,
    )
    tracker = BudgetTracker(config)
    tracker.charge(tokens=3000)
    tracker.charge(tool_calls=1)
    tracker.charge(tool_calls=1)
    tracker.charge(agent_invocations=1)

    summary = tracker.summary()
    assert summary["tokens_used"] == 3000
    assert summary["tool_calls_made"] == 2
    assert summary["agent_invocations"] == 1
    assert summary["wall_time_ms"] >= 0


def test_budget_code():
    config = BudgetConfig(max_tokens=1, max_tool_calls=100,
                          max_wall_time_ms=120_000, max_agent_invocations=8)
    tracker = BudgetTracker(config)
    tracker.charge(tokens=100)
    result = tracker.check()
    assert result.code == "budget_exceeded"


def test_charge_returns_the_check_after_adding_usage():
    tracker = BudgetTracker(BudgetConfig(max_tokens=100, max_tool_calls=1,
                                         max_wall_time_ms=120_000, max_agent_invocations=1))

    assert tracker.charge(tokens=100, tool_calls=1, agent_invocations=1).exceeded is False
    assert tracker.charge(tokens=1).exceeded is True
