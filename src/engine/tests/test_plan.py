"""Tests for the plan step (single-agent ReAct path)."""

from __future__ import annotations

import pytest

from engine.graph.plan import plan_react


async def test_plan_react_single_agent():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help me understand recursion",
        "interpretation": {
            "action": "explain",
            "agent": "tutor",
            "parameters": {"topic": "recursion"},
            "confidence": 0.95,
        },
        "events_emitted": [],
    }

    result = await plan_react(state)
    plan = result["plan"]
    assert plan["strategy"] == "react"
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["agent"] == "tutor"
    assert result["plan_cursor"] == 0


async def test_plan_react_emits_plan_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Grade essay 3",
        "interpretation": {
            "action": "grade",
            "agent": "grading_assistant",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_react(state)
    plan_events = [e for e in result["events_emitted"] if e["event"] == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["payload"]["strategy"] == "react"
    assert plan_events[0]["payload"]["steps"][0]["agent"] == "grading_assistant"


async def test_plan_react_emits_reasoning_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Draft announcement",
        "interpretation": {
            "action": "draft",
            "agent": "communication",
            "parameters": {},
            "confidence": 0.85,
        },
        "events_emitted": [],
    }

    result = await plan_react(state)
    reasoning_events = [e for e in result["events_emitted"] if e["event"] == "reasoning"]
    assert len(reasoning_events) == 1
    assert "communication" in reasoning_events[0]["payload"]["text"]


async def test_plan_react_no_interpretation():
    """Plan with no interpretation should produce empty steps."""
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "",
        "interpretation": None,
        "events_emitted": [],
    }

    result = await plan_react(state)
    assert result["plan"]["steps"] == []


async def test_plan_react_step_has_unique_id():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Test",
        "interpretation": {
            "action": "explain",
            "agent": "tutor",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result1 = await plan_react(state)
    result2 = await plan_react(state)
    id1 = result1["plan"]["steps"][0]["step_id"]
    id2 = result2["plan"]["steps"][0]["step_id"]
    assert id1 != id2  # unique step IDs


async def test_plan_react_preserves_events():
    existing = {"event": "reasoning", "payload": {"step": "interpret", "text": "..."}}
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help",
        "interpretation": {
            "action": "explain",
            "agent": "tutor",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [existing],
    }

    result = await plan_react(state)
    assert result["events_emitted"][0] == existing
    assert len(result["events_emitted"]) == 3  # existing + plan + reasoning
