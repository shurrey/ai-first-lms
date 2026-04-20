"""Tests for the Assessment agent."""

from __future__ import annotations

import pytest

from src.agents.assessment.agent import ALLOWED_TOOLS, AssessmentAgent, BLOOM_LEVELS
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {
        "person_id": "fac-001",
        "roles": [PersonaRole.faculty],
        "display_name": "Dr. Smith",
        "course_id": "cs101",
    }
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tool_backend():
    """Return a mock tool callable that returns canned responses."""

    async def call(name: str, args: dict):
        if name == "questions.search_bank":
            return {
                "questions": [
                    {
                        "id": "q-existing-1",
                        "stem": "What is recursion?",
                        "type": "mcq",
                    }
                ]
            }
        if name == "content.retrieve":
            return {
                "id": args.get("node_id", "node-1"),
                "title": "Recursion",
                "body_md": "Recursion is a technique where a function calls itself.",
                "citations": [],
            }
        if name == "graph.node_for_outcome":
            return {
                "candidates": [
                    {"node_id": "node-recursion", "title": "Recursion", "score": 0.95},
                    {"node_id": "node-base-case", "title": "Base Case", "score": 0.88},
                ]
            }
        if name == "standards.lookup":
            return {
                "standards": [
                    {"code": "CS.3.1", "description": "Understand recursive algorithms"},
                ]
            }
        if name == "questions.create":
            return {"question_id": "q-new-001"}
        return {}

    return call


class TestAssessmentAgent:
    @pytest.mark.asyncio
    async def test_generate_mcq_questions(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["recursion"],
                "question_types": ["mcq"],
                "count": 3,
                "difficulty": "moderate",
            },
            persona,
            tools,
        )

        assert result["agent_name"] == "assessment"
        assert result["error"] is None
        out = result["output"]
        assert len(out["questions"]) == 3
        for q in out["questions"]:
            assert q["type"] == "mcq"
            assert "options" in q
            assert len(q["options"]) == 4
            assert q["bloom_level"] in BLOOM_LEVELS
            assert q["difficulty"] == "moderate"
            assert len(q["aligned_nodes"]) > 0

    @pytest.mark.asyncio
    async def test_mixed_question_types(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["sorting algorithms"],
                "question_types": ["mcq", "short_answer", "essay"],
                "count": 6,
                "difficulty": "mixed",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert len(out["questions"]) == 6
        types_seen = {q["type"] for q in out["questions"]}
        assert "mcq" in types_seen
        assert "short_answer" in types_seen
        assert "essay" in types_seen
        # Mixed difficulty should produce varied difficulties
        difficulties = {q["difficulty"] for q in out["questions"]}
        assert len(difficulties) > 1

    @pytest.mark.asyncio
    async def test_rubric_generation(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["linked lists"],
                "question_types": ["essay", "code"],
                "count": 2,
                "include_rubric": True,
            },
            persona,
            tools,
        )

        out = result["output"]
        assert out["rubric"] is not None
        assert "title" in out["rubric"]
        assert "criteria" in out["rubric"]
        assert len(out["rubric"]["criteria"]) > 0
        for criterion in out["rubric"]["criteria"]:
            assert "name" in criterion
            assert "weight" in criterion
            assert "levels" in criterion
            assert "excellent" in criterion["levels"]

    @pytest.mark.asyncio
    async def test_no_rubric_by_default(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["recursion"],
                "question_types": ["mcq"],
                "count": 1,
            },
            persona,
            tools,
        )

        out = result["output"]
        assert out["rubric"] is None

    @pytest.mark.asyncio
    async def test_warnings_for_existing_bank_items(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["recursion"],
                "question_types": ["mcq"],
                "count": 2,
            },
            persona,
            tools,
        )

        out = result["output"]
        assert any("existing" in w.lower() for w in out["warnings"])

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = AssessmentAgent()
        assert "Assessment" in agent.system_prompt
        assert "user_content" in agent.system_prompt
        assert "Bloom" in agent.system_prompt
        assert "WILL NOT" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        """Assessment agent should not be able to call tools outside its set."""
        async def noop(name, args):
            return {}

        tools = ToolBag(call_tool=noop, allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")

    @pytest.mark.asyncio
    async def test_every_question_has_required_fields(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["data structures"],
                "question_types": ["mcq", "short_answer", "code"],
                "count": 5,
                "difficulty": "advanced",
            },
            persona,
            tools,
        )

        required_fields = {"stem", "type", "answer_key", "bloom_level", "difficulty", "aligned_nodes"}
        for q in result["output"]["questions"]:
            assert required_fields.issubset(q.keys()), f"Missing fields: {required_fields - q.keys()}"

    @pytest.mark.asyncio
    async def test_tool_calls_are_recorded(self):
        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["recursion"],
                "question_types": ["mcq"],
                "count": 1,
            },
            persona,
            tools,
        )

        tool_names = [tc["tool_name"] for tc in result["tool_calls"]]
        assert "questions.search_bank" in tool_names
        assert "content.retrieve" in tool_names
        assert "graph.node_for_outcome" in tool_names
        assert "standards.lookup" in tool_names

    @pytest.mark.asyncio
    async def test_warnings_when_no_alignment(self):
        """Questions without graph alignment should produce warnings."""

        async def no_alignment_backend(name: str, args: dict):
            if name == "questions.search_bank":
                return {"questions": []}
            if name == "content.retrieve":
                return {"id": "n1", "title": "T", "body_md": "text", "citations": []}
            if name == "graph.node_for_outcome":
                return {"candidates": []}
            if name == "standards.lookup":
                return {"standards": []}
            return {}

        agent = AssessmentAgent()
        persona = _persona()
        tools = ToolBag(call_tool=no_alignment_backend, allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["obscure topic"],
                "question_types": ["short_answer"],
                "count": 2,
            },
            persona,
            tools,
        )

        out = result["output"]
        alignment_warnings = [w for w in out["warnings"] if "alignment" in w.lower()]
        assert len(alignment_warnings) >= 2
