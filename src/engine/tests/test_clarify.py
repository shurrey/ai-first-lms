"""Tests for the clarify step."""

from __future__ import annotations

import json

import pytest

from engine.graph.clarify import clarify


async def test_clarify_emits_clarify_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "clarification": "Which course are you asking about?",
        "interpretation": {"action": "explain", "agent": "tutor", "confidence": 0.4},
        "events_emitted": [],
        "needs_clarification": True,
    }

    result = await clarify(state)
    events = result["events_emitted"]

    clarify_events = [e for e in events if e["event"] == "clarify"]
    assert len(clarify_events) == 1
    assert clarify_events[0]["payload"]["question"] == "Which course are you asking about?"


async def test_clarify_emits_reasoning_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "clarification": "Please specify the topic.",
        "interpretation": None,
        "events_emitted": [],
        "needs_clarification": True,
    }

    result = await clarify(state)
    reasoning_events = [e for e in result["events_emitted"] if e["event"] == "reasoning"]
    assert len(reasoning_events) == 1
    assert reasoning_events[0]["payload"]["step"] == "clarify"


async def test_clarify_resets_needs_clarification():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "clarification": "Be more specific?",
        "interpretation": None,
        "events_emitted": [],
        "needs_clarification": True,
    }

    result = await clarify(state)
    assert result["needs_clarification"] is False


async def test_clarify_provides_options_for_unknown():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "clarification": "What would you like help with?",
        "interpretation": {"action": "unknown", "agent": "tutor", "confidence": 0.1},
        "events_emitted": [],
        "needs_clarification": True,
    }

    result = await clarify(state)
    clarify_event = [e for e in result["events_emitted"] if e["event"] == "clarify"][0]
    assert clarify_event["payload"]["options"] is not None
    assert len(clarify_event["payload"]["options"]) > 0


async def test_clarify_preserves_existing_events():
    existing_event = {"event": "reasoning", "payload": {"step": "interpret", "text": "..."}}
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "clarification": "Clarify please.",
        "interpretation": None,
        "events_emitted": [existing_event],
        "needs_clarification": True,
    }

    result = await clarify(state)
    # Should have the original + 2 new (clarify + reasoning)
    assert len(result["events_emitted"]) == 3
    assert result["events_emitted"][0] == existing_event


async def test_clarify_default_question():
    """If no clarification text is set, uses default."""
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "interpretation": None,
        "events_emitted": [],
        "needs_clarification": True,
    }

    result = await clarify(state)
    clarify_event = [e for e in result["events_emitted"] if e["event"] == "clarify"][0]
    assert "clarify" in clarify_event["payload"]["question"].lower() or len(clarify_event["payload"]["question"]) > 0
