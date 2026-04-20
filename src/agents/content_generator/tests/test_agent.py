"""Tests for the Content Generator agent."""

from __future__ import annotations

import pytest

from src.agents.content_generator.agent import (
    ALLOWED_TOOLS,
    VALID_FORMATS,
    ContentGeneratorAgent,
)
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {
        "person_id": "faculty-001",
        "roles": [PersonaRole.faculty],
        "display_name": "Dr. Smith",
        "course_id": "bio101",
    }
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tool_backend():
    """Return a mock tool callable that returns canned responses."""

    async def call(name: str, args: dict):
        if name == "content.search":
            return {
                "results": [
                    {
                        "id": "node-photosynthesis",
                        "title": "Photosynthesis",
                        "snippet": "The process by which plants convert light energy.",
                        "score": 0.95,
                    },
                    {
                        "id": "node-chloroplast",
                        "title": "Chloroplasts",
                        "snippet": "Organelles where photosynthesis occurs.",
                        "score": 0.88,
                    },
                ]
            }
        if name == "content.retrieve":
            node_id = args.get("node_id", "")
            return {
                "id": node_id,
                "title": node_id.replace("node-", "").replace("-", " ").title(),
                "body_md": f"Detailed content about {node_id}.",
                "citations": [],
            }
        if name == "content.save_draft":
            return {"draft_id": "draft-test-001"}
        if name == "graph.subgraph":
            return {
                "nodes": [
                    {"id": "node-calvin-cycle", "title": "Calvin Cycle"},
                    {"id": "node-light-reactions", "title": "Light Reactions"},
                ],
                "edges": [],
            }
        if name == "standards.lookup":
            return {
                "standards": [
                    {"code": "NGSS-LS1-5", "description": "Photosynthesis standard"}
                ]
            }
        return {}

    return call


class TestContentGeneratorAgent:
    @pytest.mark.asyncio
    async def test_summary_format(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["photosynthesis"],
                "format": "summary",
                "reading_level": "high_school",
                "length": "brief",
            },
            persona,
            tools,
        )

        assert result["agent_name"] == "content_generator"
        assert result["error"] is None
        out = result["output"]
        assert "content_md" in out
        assert "Summary" in out["content_md"]
        assert "photosynthesis" in out["content_md"].lower()
        assert len(out["citations"]) > 0
        assert out["draft_id"] == "draft-test-001"

    @pytest.mark.asyncio
    async def test_study_guide_format(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["photosynthesis"],
                "format": "study_guide",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert "Study Guide" in out["content_md"]
        assert "Learning Objectives" in out["content_md"]
        assert "Review Questions" in out["content_md"]

    @pytest.mark.asyncio
    async def test_worked_example_format(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["quadratic formula"],
                "format": "worked_example",
                "reading_level": "undergrad",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert "Worked Example" in out["content_md"]
        assert "Step" in out["content_md"]
        assert "Common Mistakes" in out["content_md"]

    @pytest.mark.asyncio
    async def test_practice_problems_format(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["recursion", "base cases"],
                "format": "practice_problems",
                "reading_level": "intro_undergrad",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert "Practice Problems" in out["content_md"]
        assert "Problem 1" in out["content_md"]
        assert "Hint" in out["content_md"]

    @pytest.mark.asyncio
    async def test_slide_deck_outline_format(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["mitosis"],
                "format": "slide_deck_outline",
                "audience": "faculty",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert "Slide Deck Outline" in out["content_md"]
        assert "Slide 1" in out["content_md"]

    @pytest.mark.asyncio
    async def test_reading_guide_format(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["evolution"],
                "format": "reading_guide",
                "reading_level": "graduate",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert "Reading Guide" in out["content_md"]
        assert "Before You Read" in out["content_md"]
        assert "After Reading" in out["content_md"]

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        """Content generator should not be able to call tools outside its allowed set."""
        async def noop_tool(name, args):
            return {}

        tools = ToolBag(call_tool=noop_tool, allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")

    @pytest.mark.asyncio
    async def test_citations_are_real_node_ids(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["photosynthesis"],
                "format": "summary",
            },
            persona,
            tools,
        )

        for cid in result["output"]["citations"]:
            assert cid.startswith("node-"), f"Citation {cid} doesn't look like a node ID"

    @pytest.mark.asyncio
    async def test_draft_is_saved(self):
        """Verify that content.save_draft is called and draft_id is returned."""
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["photosynthesis"],
                "format": "summary",
            },
            persona,
            tools,
        )

        assert result["output"]["draft_id"] == "draft-test-001"
        tool_names = [tc["tool_name"] for tc in result["tool_calls"]]
        assert "content.save_draft" in tool_names

    @pytest.mark.asyncio
    async def test_invalid_format_raises_error(self):
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["photosynthesis"],
                "format": "invalid_format",
            },
            persona,
            tools,
        )

        assert result["error"] is not None
        assert "Invalid format" in result["error"]

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = ContentGeneratorAgent()
        assert "Content Generator" in agent.system_prompt
        assert "user_content" in agent.system_prompt
        assert "WILL NOT" in agent.system_prompt
        assert "fabricate citations" in agent.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_multiple_topics_searched(self):
        """Each topic in topic_or_nodes should trigger a content.search call."""
        agent = ContentGeneratorAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "topic_or_nodes": ["recursion", "base cases", "call stack"],
                "format": "study_guide",
            },
            persona,
            tools,
        )

        search_calls = [
            tc for tc in result["tool_calls"] if tc["tool_name"] == "content.search"
        ]
        assert len(search_calls) == 3, "Should search for each topic"

    @pytest.mark.asyncio
    async def test_all_valid_formats_covered(self):
        """Verify every valid format is handled without error."""
        agent = ContentGeneratorAgent()
        persona = _persona()

        for fmt in VALID_FORMATS:
            tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)
            result = await agent.run(
                {
                    "topic_or_nodes": ["test topic"],
                    "format": fmt,
                },
                persona,
                tools,
            )
            assert result["error"] is None, f"Format '{fmt}' produced an error: {result['error']}"
            assert result["output"]["content_md"], f"Format '{fmt}' produced empty content"
