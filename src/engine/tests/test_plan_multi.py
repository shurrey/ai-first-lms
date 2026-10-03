"""Tests for the multi-agent plan step."""

from __future__ import annotations

import pytest

from engine.graph.plan import plan_multi_agent


async def test_multi_agent_identify_and_help():
    """Scenario 10: early_alert → content_generator → communication."""
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "For students struggling with Ch 5, make a study guide and send it",
        "interpretation": {
            "action": "identify_and_help",
            "agent": "early_alert",
            "parameters": {"agents": ["early_alert", "content_generator", "communication"]},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    plan = result["plan"]
    assert plan["strategy"] == "plan_then_execute"
    assert len(plan["steps"]) == 3
    assert plan["steps"][0]["agent"] == "early_alert"
    assert plan["steps"][1]["agent"] == "content_generator"
    assert plan["steps"][2]["agent"] == "communication"


async def test_multi_agent_dependencies():
    """Steps with depends_on_prev should reference the previous step."""
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Draft a syllabus",
        "interpretation": {
            "action": "syllabus_draft",
            "agent": "course_architect",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    steps = result["plan"]["steps"]
    assert len(steps) == 2
    # Second step depends on first
    assert steps[1]["depends_on"] == [steps[0]["step_id"]]
    # First step has no dependencies
    assert steps[0]["depends_on"] == []


async def test_multi_agent_parallel_steps():
    """risk_analysis: early_alert and engagement_analyst can run in parallel."""
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Who is at risk and why?",
        "interpretation": {
            "action": "risk_analysis",
            "agent": "early_alert",
            "parameters": {"agents": ["early_alert", "engagement_analyst"]},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    steps = result["plan"]["steps"]
    assert len(steps) == 2
    # engagement_analyst does NOT depend on early_alert (parallel)
    assert steps[1]["depends_on"] == []


async def test_multi_agent_emits_plan_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help students",
        "interpretation": {
            "action": "identify_and_help",
            "agent": "early_alert",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    plan_events = [e for e in result["events_emitted"] if e["event"] == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["payload"]["strategy"] == "plan_then_execute"


async def test_multi_agent_emits_reasoning_event():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help students",
        "interpretation": {
            "action": "identify_and_help",
            "agent": "early_alert",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    reasoning = [e for e in result["events_emitted"] if e["event"] == "reasoning"]
    assert len(reasoning) == 1
    assert "identify_and_help" in reasoning[0]["payload"]["text"]


async def test_multi_agent_unique_step_ids():
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help students",
        "interpretation": {
            "action": "identify_and_help",
            "agent": "early_alert",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    ids = [s["step_id"] for s in result["plan"]["steps"]]
    assert len(ids) == len(set(ids))


async def test_multi_agent_fallback_to_react():
    """Unknown multi-agent pattern falls back to single-agent react."""
    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Something unusual",
        "interpretation": {
            "action": "unusual_action",
            "agent": "tutor",
            "parameters": {},
            "confidence": 0.9,
        },
        "events_emitted": [],
    }

    result = await plan_multi_agent(state)
    assert result["plan"]["strategy"] == "react"
    assert len(result["plan"]["steps"]) == 1


def test_study_guide_steps_name_the_tools_that_save_and_send():
    from engine.graph.plan import MULTI_AGENT_PATTERNS

    steps = {s["agent"]: s["input_summary"] for s in MULTI_AGENT_PATTERNS["identify_and_help"]}

    assert "roster.list_by_course" in steps["early_alert"]
    assert "content.save_draft" in steps["content_generator"]
    assert "communications.draft_message" in steps["communication"]
    assert "communications.send_message" in steps["communication"]
