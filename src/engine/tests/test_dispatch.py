"""Tests for the dispatch step."""

from __future__ import annotations

import pytest

from engine.agents.runner import StubAgentRunner
from engine.graph.dispatch import dispatch, set_agent_runner


@pytest.fixture(autouse=True)
def _reset_runner():
    yield
    set_agent_runner(None)


async def test_dispatch_single_agent():
    runner = StubAgentRunner()
    set_agent_runner(runner)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help me understand recursion",
        "plan": {
            "strategy": "react",
            "steps": [
                {"step_id": "s1", "agent": "tutor", "input_summary": "explain", "depends_on": []},
            ],
        },
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    assert len(result["agent_results"]) == 1
    assert result["agent_results"][0]["agent"] == "tutor"
    assert result["agent_results"][0]["success"] is True
    assert len(runner.calls) == 1


async def test_dispatch_emits_agent_events():
    runner = StubAgentRunner()
    set_agent_runner(runner)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Test",
        "plan": {
            "strategy": "react",
            "steps": [
                {"step_id": "s1", "agent": "tutor", "input_summary": "test", "depends_on": []},
            ],
        },
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    event_types = [e["event"] for e in result["events_emitted"]]
    assert "agent_start" in event_types
    assert "agent_result" in event_types
    assert "reasoning" in event_types


async def test_dispatch_multi_agent_sequential():
    runner = StubAgentRunner()
    set_agent_runner(runner)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Help students",
        "persona": "faculty",
        "plan": {
            "strategy": "plan_then_execute",
            "steps": [
                {"step_id": "s1", "agent": "early_alert", "input_summary": "find", "depends_on": []},
                {"step_id": "s2", "agent": "content_generator", "input_summary": "generate",
                 "depends_on": ["s1"]},
            ],
        },
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    assert len(result["agent_results"]) == 2
    assert result["agent_results"][0]["agent"] == "early_alert"
    assert result["agent_results"][1]["agent"] == "content_generator"
    # Both should succeed
    assert all(r["success"] for r in result["agent_results"])


async def test_dispatch_parallel_agents():
    runner = StubAgentRunner()
    set_agent_runner(runner)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Analyze risk",
        "persona": "faculty",
        "plan": {
            "strategy": "plan_then_execute",
            "steps": [
                {"step_id": "s1", "agent": "early_alert", "input_summary": "risk", "depends_on": []},
                {"step_id": "s2", "agent": "engagement_analyst", "input_summary": "trends",
                 "depends_on": []},
            ],
        },
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    assert len(result["agent_results"]) == 2
    assert all(r["success"] for r in result["agent_results"])


async def test_dispatch_handles_agent_error():
    class FailingRunner:
        async def run(self, agent_name, inputs):
            if agent_name == "tutor":
                raise RuntimeError("Agent crashed")
            return {"output": {}, "cost_usd": 0, "tokens": 0, "success": True, "tool_calls": []}

    set_agent_runner(FailingRunner())

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Test",
        "plan": {
            "strategy": "react",
            "steps": [
                {"step_id": "s1", "agent": "tutor", "input_summary": "test", "depends_on": []},
            ],
        },
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    assert len(result["agent_results"]) == 1
    assert result["agent_results"][0]["success"] is False


async def test_dispatch_with_tool_calls():
    runner = StubAgentRunner(responses={
        "tutor": {
            "output": {"response_markdown": "Here's the explanation"},
            "cost_usd": 0.01,
            "tokens": 800,
            "success": True,
            "tool_calls": [
                {"tool": "content.retrieve", "arguments": {"id": "node-1"},
                 "result_summary": "Retrieved content", "latency_ms": 50, "success": True},
            ],
        },
    })
    set_agent_runner(runner)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Explain recursion",
        "plan": {
            "strategy": "react",
            "steps": [
                {"step_id": "s1", "agent": "tutor", "input_summary": "explain", "depends_on": []},
            ],
        },
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    tool_events = [e for e in result["events_emitted"] if e["event"] == "agent_tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0]["payload"]["tool"] == "content.retrieve"


async def test_dispatch_no_plan():
    runner = StubAgentRunner()
    set_agent_runner(runner)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "current_message": "Test",
        "plan": None,
        "agent_results": [],
        "events_emitted": [],
    }

    result = await dispatch(state)
    assert len(result.get("agent_results", [])) == 0


async def test_dispatch_refuses_a_background_agent_even_when_the_persona_has_it():
    runner = StubAgentRunner()
    set_agent_runner(runner)
    state = {
        "session_id": "s1", "turn_id": "t1", "current_message": "x", "persona": "student",
        "plan": {"strategy": "react", "steps": [
            {"step_id": "s1", "agent": "learning_analyst", "input_summary": "x",
             "depends_on": []}]},
        "agent_results": [], "events_emitted": [],
    }

    result = await dispatch(state)

    assert runner.calls == []
    assert result["turn_error"]["code"] == "permission_denied"


async def test_dispatch_carries_the_ai_action_ids_the_step_wrote():
    class WritingRunner:
        async def run(self, agent_name, inputs):
            inputs["_tool_context"].ai_action_ids.extend(["act-1", "act-2"])
            return {"output": {}, "cost_usd": 0, "tokens": 0, "success": True, "tool_calls": []}

    set_agent_runner(WritingRunner())
    state = {
        "session_id": "s1", "turn_id": "t1", "current_message": "Test",
        "plan": {"strategy": "react", "steps": [
            {"step_id": "s1", "agent": "tutor", "input_summary": "test", "depends_on": []}]},
        "agent_results": [], "events_emitted": [],
    }

    result = await dispatch(state)

    assert result["agent_results"][0]["ai_action_ids"] == ["act-1", "act-2"]
    [agent_result] = [e for e in result["events_emitted"] if e["event"] == "agent_result"]
    assert "ai_action_ids" not in agent_result["payload"]
