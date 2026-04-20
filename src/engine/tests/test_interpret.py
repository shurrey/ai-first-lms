"""Tests for the interpret step with mocked LLM responses."""

from __future__ import annotations

import json

import pytest

from engine.graph.interpret import interpret, set_llm_client


class MockLLMClient:
    """Mock LLM client that returns canned responses."""

    def __init__(self, response: dict) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def create_message(
        self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> str:
        self.calls.append({"model": model, "messages": messages})
        return json.dumps(self._response)


@pytest.fixture(autouse=True)
def _reset_client():
    yield
    set_llm_client(None)


async def test_interpret_high_confidence():
    mock = MockLLMClient({
        "action": "explain",
        "agent": "tutor",
        "parameters": {"topic": "recursion"},
        "confidence": 0.95,
        "needs_clarification": False,
        "clarification_reason": None,
    })
    set_llm_client(mock)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "persona": "student",
        "current_message": "Help me understand recursion",
        "events_emitted": [],
    }

    result = await interpret(state)

    assert result["interpretation"]["action"] == "explain"
    assert result["interpretation"]["agent"] == "tutor"
    assert result["interpretation"]["confidence"] == 0.95
    assert result["needs_clarification"] is False
    assert len(mock.calls) == 1


async def test_interpret_low_confidence_triggers_clarification():
    mock = MockLLMClient({
        "action": "unknown",
        "agent": "tutor",
        "parameters": {},
        "confidence": 0.3,
        "needs_clarification": True,
        "clarification_reason": "Ambiguous request",
    })
    set_llm_client(mock)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "persona": "student",
        "current_message": "help",
        "events_emitted": [],
    }

    result = await interpret(state)
    assert result["needs_clarification"] is True
    assert result["clarification"] == "Ambiguous request"


async def test_interpret_emits_reasoning_event():
    mock = MockLLMClient({
        "action": "grade",
        "agent": "grading_assistant",
        "parameters": {},
        "confidence": 0.9,
        "needs_clarification": False,
        "clarification_reason": None,
    })
    set_llm_client(mock)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "persona": "faculty",
        "current_message": "Grade essay 3 submissions",
        "events_emitted": [],
    }

    result = await interpret(state)
    events = result["events_emitted"]
    assert len(events) == 1
    assert events[0]["event"] == "reasoning"
    assert events[0]["payload"]["step"] == "interpret"
    assert "grading_assistant" in events[0]["payload"]["text"]


async def test_interpret_handles_malformed_llm_response():
    """If LLM returns garbage, interpret should gracefully degrade."""

    class BadLLM:
        async def create_message(self, **kwargs) -> str:
            return "not valid json at all"

    set_llm_client(BadLLM())

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "persona": "student",
        "current_message": "something",
        "events_emitted": [],
    }

    result = await interpret(state)
    assert result["needs_clarification"] is True
    assert result["interpretation"]["confidence"] == 0.0


async def test_interpret_passes_persona_to_llm():
    mock = MockLLMClient({
        "action": "advise",
        "agent": "advising",
        "parameters": {},
        "confidence": 0.85,
        "needs_clarification": False,
        "clarification_reason": None,
    })
    set_llm_client(mock)

    state = {
        "session_id": "s1",
        "turn_id": "t1",
        "persona": "advisor",
        "current_message": "Show at-risk students",
        "events_emitted": [],
    }

    await interpret(state)
    sent_message = mock.calls[0]["messages"][0]["content"]
    assert "advisor" in sent_message
