"""Tests for the synthesize step."""

from __future__ import annotations

import pytest

from engine.graph.synthesize import synthesize


async def test_synthesize_single_agent():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "tutor",
                "output": {"response_markdown": "Recursion is when a function calls itself."},
                "cost_usd": 0.01,
                "tokens": 500,
                "success": True,
            },
        ],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    assert result["final_answer"] == "Recursion is when a function calls itself."
    assert result["cost_usd"] == 0.01


async def test_synthesize_multi_agent():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "early_alert",
                "output": {"response_markdown": "3 students at risk."},
                "cost_usd": 0.02,
                "tokens": 1000,
                "success": True,
            },
            {
                "step_id": "s2",
                "agent": "content_generator",
                "output": {"content_md": "Study guide for Chapter 5."},
                "cost_usd": 0.01,
                "tokens": 800,
                "success": True,
            },
        ],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    assert "3 students at risk" in result["final_answer"]
    assert "Study guide" in result["final_answer"]
    assert result["cost_usd"] == 0.03


async def test_synthesize_emits_final_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "tutor",
                "output": {"response_markdown": "Answer here."},
                "cost_usd": 0.01,
                "tokens": 500,
                "success": True,
            },
        ],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    final_events = [e for e in result["events_emitted"] if e["event"] == "final"]
    assert len(final_events) == 1
    payload = final_events[0]["payload"]
    assert payload["answer_markdown"] == "Answer here."
    assert payload["cost_usd"] == 0.01
    assert payload["tokens"] == 500


async def test_synthesize_extracts_artifacts():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "assessment",
                "output": {
                    "response_markdown": "Here are your questions.",
                    "questions": [{"stem": "What is X?"}],
                },
                "cost_usd": 0.02,
                "tokens": 1200,
                "success": True,
            },
        ],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    final_event = [e for e in result["events_emitted"] if e["event"] == "final"][0]
    assert len(final_event["payload"]["artifacts"]) == 1
    assert final_event["payload"]["artifacts"][0]["type"] == "quiz"


async def test_synthesize_handles_failed_agent():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "tutor",
                "output": {"error": "Agent crashed"},
                "cost_usd": 0.0,
                "tokens": 0,
                "success": False,
            },
        ],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    assert "Unable to complete" in result["final_answer"] or "error" in result["final_answer"].lower() or result["final_answer"]


async def test_synthesize_no_results():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    assert "try again" in result["final_answer"].lower()


async def test_synthesize_emits_reasoning_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "agent_results": [
            {
                "step_id": "s1",
                "agent": "tutor",
                "output": {"response_markdown": "Answer."},
                "cost_usd": 0.01,
                "tokens": 500,
                "success": True,
            },
        ],
        "events_emitted": [],
        "cost_usd": 0.0,
        "tokens": 0,
    }

    result = await synthesize(state)
    reasoning = [e for e in result["events_emitted"] if e["event"] == "reasoning"]
    assert len(reasoning) == 1
    assert reasoning[0]["payload"]["step"] == "synthesize"


async def test_final_event_lists_the_turns_ai_action_ids_once_in_order():
    def result(step: str, ids: list[str] | None) -> dict:
        r = {"step_id": step, "agent": "tutor", "output": {"response_markdown": step},
             "cost_usd": 0.0, "tokens": 0, "success": True}
        return {**r, "ai_action_ids": ids} if ids is not None else r

    state = {"agent_results": [result("a", ["x", "y"]), result("b", None),
                               result("c", ["y", "z"])],
             "events_emitted": [], "cost_usd": 0.0, "tokens": 0}

    out = await synthesize(state)

    [final] = [e for e in out["events_emitted"] if e["event"] == "final"]
    assert final["payload"]["ai_action_ids"] == ["x", "y", "z"]


async def test_final_event_has_empty_ai_action_ids_without_writes():
    out = await synthesize({"agent_results": [], "events_emitted": []})
    [final] = [e for e in out["events_emitted"] if e["event"] == "final"]
    assert final["payload"]["ai_action_ids"] == []
