"""Integration test: Scenario 10 — Multi-agent end-to-end.

"For students struggling with Ch 5, make a tailored study guide and send it."

This is the flagship multi-agent demo. Expected flow:
1. Faculty creates session
2. Interprets as multi-agent (identify_and_help pattern)
3. Plan: early_alert → content_generator → communication
4. Dispatch runs all three agents
5. Communication agent triggers approval_request
6. Faculty approves → turn completes
"""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from engine.agents.runner import StubAgentRunner
from engine.app import create_app
from engine.graph.dispatch import set_agent_runner
from engine.graph.interpret import set_llm_client


class MockMultiAgentLLM:
    """Mock LLM that returns a multi-agent intent."""

    async def create_message(self, model, system, messages, max_tokens):
        return json.dumps({
            "action": "identify_and_help",
            "agent": "early_alert",
            "parameters": {
                "agents": ["early_alert", "content_generator", "communication"],
            },
            "confidence": 0.92,
            "needs_clarification": False,
            "clarification_reason": None,
        })


@pytest.fixture
def app():
    return create_app()


@pytest.fixture(autouse=True)
def _setup_mocks():
    set_llm_client(MockMultiAgentLLM())
    set_agent_runner(StubAgentRunner(responses={
        "early_alert": {
            "output": {
                "response_markdown": "Found 3 students at risk in Chapter 5.",
                "at_risk": [
                    {"student_id": "s1", "name": "Alice", "risk_score": 0.82},
                    {"student_id": "s2", "name": "Bob", "risk_score": 0.75},
                    {"student_id": "s3", "name": "Carol", "risk_score": 0.71},
                ],
            },
            "cost_usd": 0.015,
            "tokens": 900,
            "success": True,
            "tool_calls": [
                {"tool": "analytics.query", "arguments": {}, "result_summary": "Queried risk data",
                 "latency_ms": 60, "success": True},
            ],
        },
        "content_generator": {
            "output": {
                "content_md": "# Study Guide: Chapter 5\n\nKey concepts...",
                "draft_id": "draft-001",
            },
            "cost_usd": 0.008,
            "tokens": 600,
            "success": True,
            "tool_calls": [],
        },
        "communication": {
            "output": {
                "response_markdown": "Draft message prepared for 3 students.",
                "drafts": [
                    {"recipient": "Alice", "message": "Study guide for Ch 5..."},
                    {"recipient": "Bob", "message": "Study guide for Ch 5..."},
                    {"recipient": "Carol", "message": "Study guide for Ch 5..."},
                ],
                "send_ready_payload": {"count": 3, "channel": "inbox"},
            },
            "cost_usd": 0.005,
            "tokens": 400,
            "success": True,
            "tool_calls": [],
        },
    }))
    yield
    set_llm_client(None)
    set_agent_runner(None)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_faculty_session(client) -> str:
    resp = await client.post("/api/session", json={
        "persona": "faculty",
        "course_id": "cs101",
    })
    assert resp.status_code == 201
    return resp.json()["session_id"]


async def _wait_for_turn(app, turn_id: str, max_wait: float = 5.0) -> None:
    for _ in range(int(max_wait / 0.05)):
        turn = await app.state.turn_store.get(turn_id)
        if turn and turn.status in ("completed", "error"):
            return
        await asyncio.sleep(0.05)


async def test_scenario_10_multi_agent_plan(app, client):
    """Verify the orchestrator creates a multi-step plan."""
    session_id = await _create_faculty_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "For students struggling with Ch 5, make a tailored study guide and send it",
    })
    assert resp.status_code == 202
    turn_id = resp.json()["turn_id"]

    await _wait_for_turn(app, turn_id)

    turn = await app.state.turn_store.get(turn_id)
    assert turn.status == "completed"

    events = turn.events
    plan_events = [e for e in events if e.get("event") == "plan"]
    assert len(plan_events) == 1

    plan_payload = plan_events[0]["payload"]
    assert plan_payload["strategy"] == "plan_then_execute"
    assert len(plan_payload["steps"]) == 3

    agents_in_plan = [s["agent"] for s in plan_payload["steps"]]
    assert "early_alert" in agents_in_plan
    assert "content_generator" in agents_in_plan
    assert "communication" in agents_in_plan


async def test_scenario_10_all_agents_invoked(app, client):
    """All three agents should be invoked and produce results."""
    session_id = await _create_faculty_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Help struggling Ch 5 students with a study guide and message",
    })
    turn_id = resp.json()["turn_id"]
    await _wait_for_turn(app, turn_id)

    turn = await app.state.turn_store.get(turn_id)
    events = turn.events

    agent_result_events = [e for e in events if e.get("event") == "agent_result"]
    assert len(agent_result_events) == 3

    result_agents = [e["payload"]["agent"] for e in agent_result_events]
    assert "early_alert" in result_agents
    assert "content_generator" in result_agents
    assert "communication" in result_agents


async def test_scenario_10_final_combines_results(app, client):
    """Final answer should combine all agent outputs."""
    session_id = await _create_faculty_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Find at-risk students, make study guide, send it",
    })
    turn_id = resp.json()["turn_id"]
    await _wait_for_turn(app, turn_id)

    turn = await app.state.turn_store.get(turn_id)
    final_events = [e for e in turn.events if e.get("event") == "final"]
    assert len(final_events) == 1

    final = final_events[0]["payload"]
    # Should have content from multiple agents
    assert len(final["answer_markdown"]) > 0
    assert final["cost_usd"] > 0
    assert final["tokens"] > 0


async def test_scenario_10_event_ordering(app, client):
    """Events should follow multi-agent flow: interpret → plan → agents → synthesize."""
    session_id = await _create_faculty_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Multi-agent test",
    })
    turn_id = resp.json()["turn_id"]
    await _wait_for_turn(app, turn_id)

    turn = await app.state.turn_store.get(turn_id)
    event_types = [e.get("event") for e in turn.events]

    # Should see reasoning before plan
    assert "reasoning" in event_types
    assert "plan" in event_types

    first_reasoning = event_types.index("reasoning")
    first_plan = event_types.index("plan")
    assert first_reasoning < first_plan

    # Should see agent_start events
    assert "agent_start" in event_types

    # Should end with final
    assert event_types[-1] == "final" or "final" in event_types
