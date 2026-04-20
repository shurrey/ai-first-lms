"""Tests for the Tutor agent."""

from __future__ import annotations

import pytest

from src.agents.tutor.agent import ALLOWED_TOOLS, TutorAgent
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {
        "person_id": "stu-001",
        "roles": [PersonaRole.student],
        "display_name": "Alice",
        "course_id": "cs101",
    }
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tool_backend():
    """Return a mock tool callable that returns canned responses."""
    async def call(name: str, args: dict):
        if name == "content.search":
            return {
                "results": [
                    {"id": "node-recursion", "title": "Recursion", "snippet": "A function that calls itself.", "score": 0.95},
                    {"id": "node-base-case", "title": "Base Case", "snippet": "The terminating condition.", "score": 0.88},
                ]
            }
        if name == "roster.get_student_context":
            return {
                "recent_evidence": [{"node_id": "node-recursion", "score": 0.6}],
                "current_modules": ["mod-04-functions"],
                "upcoming_assignments": ["hw-03"],
            }
        if name == "assessments.list_recent_evidence":
            return {
                "evidence": [
                    {"node_id": "node-recursion", "score": 0.6, "kind": "attempt"},
                    {"node_id": "node-loops", "score": 0.9, "kind": "completion"},
                ]
            }
        if name == "graph.neighbors":
            return {
                "nodes": [
                    {"id": "node-base-case", "title": "Base Case"},
                    {"id": "node-stack", "title": "Call Stack"},
                    {"id": "node-iteration", "title": "Iteration"},
                ],
                "edges": [],
            }
        if name == "graph.path_to_mastery":
            return {"path": [{"node_id": "node-recursion", "mastery_level": "emerging", "confidence": 0.7}]}
        return {}
    return call


class TestTutorAgent:
    @pytest.mark.asyncio
    async def test_explain_mode(self):
        agent = TutorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"query": "recursion", "course_id": "cs101", "mode": "explain"},
            persona,
            tools,
        )

        assert result["agent_name"] == "tutor"
        assert result["error"] is None
        out = result["output"]
        assert "recursion" in out["response_markdown"].lower()
        assert "node-recursion" in out["citations"]
        assert len(out["follow_ups"]) > 0
        assert len(out["suggested_nodes"]) > 0

    @pytest.mark.asyncio
    async def test_quiz_me_mode(self):
        agent = TutorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"query": "loops", "course_id": "cs101", "mode": "quiz_me"},
            persona,
            tools,
        )

        out = result["output"]
        assert "test your understanding" in out["response_markdown"].lower()
        assert len(out["citations"]) >= 1

    @pytest.mark.asyncio
    async def test_find_weakness_mode(self):
        agent = TutorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"query": "what am I bad at", "course_id": "cs101", "mode": "find_weakness"},
            persona,
            tools,
        )

        out = result["output"]
        assert "focus" in out["response_markdown"].lower()
        # Should have called assessments.list_recent_evidence
        tool_names = [tc["tool_name"] for tc in result["tool_calls"]]
        assert "assessments.list_recent_evidence" in tool_names

    @pytest.mark.asyncio
    async def test_default_mode_is_explain(self):
        agent = TutorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"query": "variables", "course_id": "cs101"},
            persona,
            tools,
        )

        out = result["output"]
        assert "walk you through" in out["response_markdown"].lower()

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = TutorAgent()
        assert "Tutor" in agent.system_prompt
        assert "user_content" in agent.system_prompt
        assert "Socratic" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        """Tutor should not be able to call tools outside its allowed set."""
        agent = TutorAgent()

        async def bad_tool_call(name, args):
            return {}

        tools = ToolBag(call_tool=bad_tool_call, allowed_tools=ALLOWED_TOOLS)
        # Direct call to a disallowed tool should fail
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")

    @pytest.mark.asyncio
    async def test_citations_are_real_node_ids(self):
        agent = TutorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"query": "recursion", "course_id": "cs101"},
            persona,
            tools,
        )

        for cid in result["output"]["citations"]:
            assert cid.startswith("node-"), f"Citation {cid} doesn't look like a node ID"
