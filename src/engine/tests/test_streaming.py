"""Tests for SSE streaming helper per contracts/events.md."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.streaming.events import (
    ErrorPayload,
    EventEnvelope,
    FinalPayload,
    ReasoningPayload,
)
from engine.streaming.sse import stream_events


def _make_envelope(seq: int, event: str = "reasoning", **kwargs) -> EventEnvelope:
    payload_map = {
        "reasoning": ReasoningPayload(step="interpret", text=f"step {seq}"),
        "final": FinalPayload(
            answer_markdown="done", artifacts=[], cost_usd=0.01, tokens=100, wall_time_ms=500
        ),
        "error": ErrorPayload(code="internal", message="boom", retriable=False),
    }
    return EventEnvelope(
        event=event,
        session_id="sess-1",
        turn_id="turn-1",
        sequence=seq,
        payload=kwargs.get("payload", payload_map[event]),
    )


async def _async_iter(items: list[EventEnvelope]) -> AsyncIterator[EventEnvelope]:
    for item in items:
        yield item


async def test_stream_events_returns_event_source_response():
    events = [_make_envelope(1), _make_envelope(2)]
    response = stream_events(_async_iter(events))
    assert response.media_type == "text/event-stream"


async def test_envelope_conforms_to_contract():
    envelope = _make_envelope(1)
    data = envelope.model_dump()
    assert "event" in data
    assert "session_id" in data
    assert "turn_id" in data
    assert "sequence" in data
    assert "timestamp" in data
    assert "payload" in data
    assert data["sequence"] == 1


async def test_sequence_is_monotonic():
    envelopes = [_make_envelope(i) for i in range(1, 6)]
    sequences = [e.sequence for e in envelopes]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


async def test_all_event_types_serialize():
    """Every event type from contracts/events.md can be serialized."""
    from engine.streaming.events import (
        AgentResultPayload,
        AgentStartPayload,
        AgentTokenPayload,
        AgentToolCallPayload,
        ApprovalRequestPayload,
        ClarifyPayload,
        PlanPayload,
        PlanStepPayload,
    )

    payloads = [
        ("reasoning", ReasoningPayload(step="interpret", text="thinking")),
        ("plan", PlanPayload(
            strategy="react",
            steps=[PlanStepPayload(step_id="s1", agent="tutor", input_summary="explain")],
            estimated_cost_usd=0.01, estimated_tokens=1000,
        )),
        ("agent_start", AgentStartPayload(step_id="s1", agent="tutor", inputs={"q": "hi"})),
        ("agent_token", AgentTokenPayload(
            step_id="s1", agent="tutor", delta="hello", channel="response"
        )),
        ("agent_tool_call", AgentToolCallPayload(
            step_id="s1", agent="tutor", tool="content.retrieve",
            arguments={"id": "1"}, result_summary="ok", latency_ms=50, success=True,
        )),
        ("agent_result", AgentResultPayload(
            step_id="s1", agent="tutor", output={"text": "done"},
            cost_usd=0.01, tokens=500, success=True,
        )),
        ("clarify", ClarifyPayload(question="which?", reason="ambiguous")),
        ("approval_request", ApprovalRequestPayload(
            approval_id="a1", step_id="s1", agent="grading_assistant",
            action="commit grades", preview={"grades": []}, artifact_type="rubric_grades",
        )),
        ("final", FinalPayload(
            answer_markdown="done", artifacts=[], cost_usd=0.02, tokens=1000, wall_time_ms=800,
        )),
        ("error", ErrorPayload(code="budget_exceeded", message="over limit", retriable=False)),
    ]

    for event_type, payload in payloads:
        envelope = EventEnvelope(
            event=event_type,
            session_id="sess-1",
            turn_id="turn-1",
            sequence=1,
            payload=payload,
        )
        serialized = json.loads(envelope.model_dump_json())
        assert serialized["event"] == event_type


async def test_sse_endpoint_integration():
    """Integration test: wire stream_events into a FastAPI app and read SSE."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/test-stream")
    async def test_stream():
        events = [_make_envelope(1), _make_envelope(2)]
        return stream_events(_async_iter(events))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test-stream")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        # Body should contain SSE-formatted data lines
        body = resp.text
        assert "event: reasoning" in body
        assert '"session_id": "sess-1"' in body


async def test_disconnect_cleanup():
    """Generator should handle cancellation without leaking."""
    import asyncio

    source_closed = False

    async def slow_source() -> AsyncIterator[EventEnvelope]:
        nonlocal source_closed
        try:
            yield _make_envelope(1)
            await asyncio.sleep(100)  # simulate long-running source
            yield _make_envelope(2)
        finally:
            source_closed = True

    from engine.streaming.sse import _event_generator

    gen = _event_generator(slow_source())
    first = await gen.__anext__()
    assert first["event"] == "reasoning"
    await gen.aclose()
    # The inner source generator should have been cleaned up via finally
    assert source_closed
