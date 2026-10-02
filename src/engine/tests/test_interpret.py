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


async def test_prompt_lists_agents_allowed_for_persona():
    class Capture:
        prompt = ""

        async def create_message(self, model, system, messages, max_tokens):
            Capture.prompt = messages[0]["content"]
            return '{"action": "advise", "agent": "advising", "confidence": 0.9}'

    set_llm_client(Capture())
    try:
        await interpret({"current_message": "What next?", "persona": "advisor"})
    finally:
        set_llm_client(None)

    allowed_line = next(l for l in Capture.prompt.splitlines() if l.startswith("Allowed agents:"))
    assert "advising" in allowed_line
    assert "tutor" not in allowed_line


async def test_interpret_charges_classifier_tokens_to_turn_budget():
    from engine.guardrails.budget import BudgetConfig, BudgetTracker

    class UsageLLM:
        async def create_message_with_usage(self, **kwargs) -> tuple[str, int]:
            return json.dumps({"action": "explain", "agent": "tutor", "confidence": 0.9}), 321

    set_llm_client(UsageLLM())
    budget = BudgetTracker(BudgetConfig(max_tokens=10_000, max_tool_calls=10,
                                        max_wall_time_ms=60_000, max_agent_invocations=8))
    state = {
        "persona": "student",
        "current_message": "explain recursion",
        "events_emitted": [],
        "budget": budget,
    }

    await interpret(state)
    assert budget.tokens_used == 321


async def test_interpret_accepts_fenced_json():
    class FencedLLM:
        async def create_message(self, **kwargs) -> str:
            return '```json\n{"action": "explain", "agent": "tutor", "confidence": 0.95}\n```'

    set_llm_client(FencedLLM())
    result = await interpret({"persona": "student", "current_message": "hi", "events_emitted": []})
    assert result["needs_clarification"] is False
    assert result["interpretation"]["agent"] == "tutor"


def test_default_agent_respects_persona_scope() -> None:
    from engine.graph.interpret import _default_agent

    assert _default_agent({"tutor", "assessment"}) == "tutor"
    assert _default_agent({"early_alert", "advising", "communication"}) == "early_alert"
    assert _default_agent({"accessibility"}) == "accessibility"


def _student_state() -> dict:
    return {"session_id": "s1", "turn_id": "t1", "persona": "student",
            "current_message": "Summarise my session", "events_emitted": []}


async def test_classifier_cannot_route_a_student_to_learning_analyst(caplog):
    set_llm_client(MockLLMClient({"action": "analyze", "agent": "learning_analyst",
                                  "parameters": {}, "confidence": 0.95}))

    with caplog.at_level("WARNING", logger="engine.graph.interpret"):
        result = await interpret(_student_state())

    assert result["interpretation"]["agent"] == "tutor"
    assert "learning_analyst" in caplog.text


async def test_classifier_cannot_route_a_student_to_a_staff_agent():
    set_llm_client(MockLLMClient({"action": "grade", "agent": "grading_assistant",
                                  "parameters": {}, "confidence": 0.95}))

    result = await interpret(_student_state())

    assert result["interpretation"]["agent"] == "tutor"


async def test_unknown_agent_name_falls_back_to_the_persona_default():
    set_llm_client(MockLLMClient({"action": "x", "agent": {"name": "tutor"},
                                  "parameters": {}, "confidence": 0.95}))

    result = await interpret(_student_state())

    assert result["interpretation"]["agent"] == "tutor"


async def test_multi_agent_list_is_limited_to_routable_agents_for_the_persona():
    set_llm_client(MockLLMClient({
        "action": "risk_analysis", "agent": "early_alert",
        "parameters": {"agents": ["early_alert", "learning_analyst", "engagement_analyst"]},
        "confidence": 0.95,
    }))
    state = {**_student_state(), "persona": "faculty"}

    result = await interpret(state)

    assert result["interpretation"]["parameters"]["agents"] == [
        "early_alert", "engagement_analyst"]


def test_every_persona_has_routable_agents_and_a_default():
    from engine.graph.interpret import ROUTABLE_AGENTS, _default_agent
    from engine.guardrails.registry import get_permission_matrix

    matrix = get_permission_matrix()
    expected_default = {
        "student": "tutor", "faculty": "tutor", "advisor": "advising",
        "admin": "engagement_analyst", "program_lead": "engagement_analyst",
    }
    for persona, default in expected_default.items():
        allowed = frozenset(matrix.allowed_agents(persona)) & ROUTABLE_AGENTS
        assert len(allowed) >= 4, persona
        assert _default_agent(allowed, persona) == default
