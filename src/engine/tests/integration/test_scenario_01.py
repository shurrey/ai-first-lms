"""Integration test: Scenario 1 — Student asks a tutoring question (end-to-end).

Uses mocked agent responses. The full flow is:
1. Create session (student persona)
2. POST /api/converse with a tutoring question
3. Wait for graph completion
4. GET /api/stream to collect all events
5. Verify event sequence and final answer
"""

from __future__ import annotations

import asyncio
import json

import pytest

from engine.agents.runner import StubAgentRunner
from engine.graph.dispatch import set_agent_runner
from engine.graph.interpret import set_llm_client


class MockInterpretLLM:
    """Mock LLM that returns a tutor intent."""

    async def create_message(self, model, system, messages, max_tokens):
        return json.dumps({
            "action": "explain",
            "agent": "tutor",
            "parameters": {"topic": "recursion"},
            "confidence": 0.95,
            "needs_clarification": False,
            "clarification_reason": None,
        })


@pytest.fixture
def app(auth_app):
    return auth_app


@pytest.fixture(autouse=True)
def _setup_mocks():
    """Set up mocked LLM and agent runner."""
    set_llm_client(MockInterpretLLM())
    set_agent_runner(StubAgentRunner(responses={
        "tutor": {
            "output": {
                "response_markdown": "Recursion is when a function calls itself. "
                "The key idea is a base case that stops the recursion.",
                "citations": ["CS101 Module 5"],
                "follow_ups": ["Can you give me an example?"],
            },
            "cost_usd": 0.008,
            "tokens": 650,
            "success": True,
            "tool_calls": [
                {
                    "tool": "content.retrieve",
                    "arguments": {"topic": "recursion"},
                    "result_summary": "Retrieved recursion content",
                    "latency_ms": 45,
                    "success": True,
                },
            ],
        },
    }))
    yield
    set_llm_client(None)
    set_agent_runner(None)


@pytest.fixture
async def client(authed_client):
    return await authed_client("student")


async def _create_student_session(client) -> str:
    resp = await client.post("/api/session", json={
        "course_id": "cs101",
    })
    assert resp.status_code == 201
    return resp.json()["session_id"]


async def test_scenario_01_full_flow(app, client):
    """Full end-to-end: student asks about recursion."""
    # 1. Create session
    session_id = await _create_student_session(client)

    # 2. Post tutoring question
    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Can you help me understand recursion?",
    })
    assert resp.status_code == 202
    data = resp.json()
    turn_id = data["turn_id"]
    stream_url = data["stream_url"]

    # 3. Wait for the graph to complete
    for _ in range(50):
        turn = await app.state.turn_store.get(turn_id)
        if turn and turn.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    # 4. Verify turn completed
    turn = await app.state.turn_store.get(turn_id)
    assert turn is not None
    assert turn.status == "completed"

    # 5. Check events were generated
    events = turn.events
    assert len(events) > 0

    event_types = [e.get("event") for e in events]

    # Should have reasoning events
    assert "reasoning" in event_types

    # Should have plan event
    assert "plan" in event_types

    # Should have agent_start
    assert "agent_start" in event_types

    # Should have agent_result
    assert "agent_result" in event_types

    # Should have final event
    assert "final" in event_types


async def test_scenario_01_stream_endpoint(app, client):
    """Verify the SSE stream returns events."""
    session_id = await _create_student_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Explain recursion step by step",
    })
    turn_id = resp.json()["turn_id"]

    # Wait for completion
    for _ in range(50):
        turn = await app.state.turn_store.get(turn_id)
        if turn and turn.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    # Get events via stream endpoint
    resp = await client.get(
        f"/api/stream?session_id={session_id}&turn_id={turn_id}"
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "reasoning" in body


async def test_scenario_01_event_order(app, client):
    """Events should follow the expected orchestrator flow order."""
    session_id = await _create_student_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "What is recursion?",
    })
    turn_id = resp.json()["turn_id"]

    for _ in range(50):
        turn = await app.state.turn_store.get(turn_id)
        if turn and turn.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    events = turn.events
    event_types = [e.get("event") for e in events]

    # reasoning (interpret) should come before plan
    first_reasoning = event_types.index("reasoning")
    first_plan = event_types.index("plan")
    assert first_reasoning < first_plan

    # plan should come before agent_start
    first_agent_start = event_types.index("agent_start")
    assert first_plan < first_agent_start

    # agent_result should come before final
    if "agent_result" in event_types and "final" in event_types:
        first_result = event_types.index("agent_result")
        first_final = event_types.index("final")
        assert first_result < first_final


async def test_scenario_01_final_answer_content(app, client):
    """Final answer should contain relevant content about recursion."""
    session_id = await _create_student_session(client)

    resp = await client.post("/api/converse", json={
        "session_id": session_id,
        "message": "Help me understand recursion",
    })
    turn_id = resp.json()["turn_id"]

    for _ in range(50):
        turn = await app.state.turn_store.get(turn_id)
        if turn and turn.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    events = turn.events
    final_events = [e for e in events if e.get("event") == "final"]
    assert len(final_events) == 1

    final_payload = final_events[0]["payload"]
    assert "recursion" in final_payload["answer_markdown"].lower()
