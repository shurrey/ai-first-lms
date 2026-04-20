"""Tests for the LangGraph orchestrator state machine."""

from __future__ import annotations

import json

import pytest

from engine.graph.builder import build_graph
from engine.graph.dispatch import set_agent_runner
from engine.graph.interpret import set_llm_client
from engine.graph.state import OrchestratorState


class _MockLLM:
    async def create_message(self, model, system, messages, max_tokens):
        return json.dumps({
            "action": "explain", "agent": "tutor", "parameters": {},
            "confidence": 0.95, "needs_clarification": False, "clarification_reason": None,
        })


@pytest.fixture(autouse=True)
def _mock_deps():
    from engine.agents.runner import StubAgentRunner
    set_llm_client(_MockLLM())
    set_agent_runner(StubAgentRunner())
    yield
    set_llm_client(None)
    set_agent_runner(None)


def test_graph_compiles():
    """Graph should compile without error."""
    graph = build_graph()
    compiled = graph.compile()
    assert compiled is not None


async def test_happy_path_traversal():
    """Simple input traverses interpret → plan → dispatch → synthesize."""
    graph = build_graph()
    compiled = graph.compile()

    initial_state: OrchestratorState = {
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "persona": "student",
        "course_id": "cs101",
        "conversation": [],
        "current_message": "Help me understand recursion",
        "interpretation": None,
        "clarification": None,
        "plan": None,
        "plan_cursor": 0,
        "agent_results": [],
        "pending_approvals": [],
        "final_answer": None,
        "cost_usd": 0.0,
        "tokens": 0,
        "budget_exceeded": False,
        "events_emitted": [],
        "needs_clarification": False,
    }

    result = await compiled.ainvoke(initial_state)

    # Should have gone through all steps and produced a final answer
    assert result["final_answer"] is not None
    assert result["interpretation"] is not None
    assert result["plan"] is not None
    assert len(result["agent_results"]) > 0


async def test_graph_produces_plan():
    """After traversal, state should contain a valid plan."""
    graph = build_graph()
    compiled = graph.compile()

    result = await compiled.ainvoke({
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "current_message": "What should I take next semester?",
        "needs_clarification": False,
    })

    assert result["plan"] is not None
    assert result["plan"]["strategy"] in ("react", "plan_then_execute")
    assert len(result["plan"]["steps"]) > 0


def test_graph_has_expected_nodes():
    """Graph should have the five expected nodes."""
    graph = build_graph()
    expected = {"interpret", "clarify", "plan", "dispatch", "synthesize"}
    assert expected == set(graph.nodes.keys())
