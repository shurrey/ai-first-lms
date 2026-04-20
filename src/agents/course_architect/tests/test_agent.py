"""Tests for the Course Architect agent."""

from __future__ import annotations

import pytest

from src.agents.course_architect.agent import ALLOWED_TOOLS, CourseArchitectAgent
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {"person_id": "fac-001", "roles": [PersonaRole.faculty], "display_name": "Dr. Torres", "course_id": "cs101"}
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tools():
    async def call(name, args):
        if name == "standards.lookup":
            return {"standards": [{"code": "CS.1.1", "text": "Understand algorithms"}]}
        if name == "content.library_search":
            return {"items": [{"id": "lib-1", "kind": "textbook", "title": "Intro CS", "snippet": "..."}]}
        if name == "graph.subgraph_for_outcomes":
            return {"nodes": [], "edges": []}
        if name == "content.save_draft":
            return {"draft_id": "draft-syllabus-1"}
        return {}
    return call


class TestCourseArchitectAgent:
    @pytest.mark.asyncio
    async def test_basic_syllabus_draft(self):
        agent = CourseArchitectAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "topic": "Intro to Data Ethics",
            "audience": "undergrad",
            "duration_weeks": 15,
        }, _persona(), tools)
        assert result["error"] is None
        out = result["output"]
        assert len(out["outcomes"]) >= 3
        assert len(out["modules"]) > 0
        assert "Intro to Data Ethics" in out["syllabus_md"]

    @pytest.mark.asyncio
    async def test_outcomes_have_bloom_levels(self):
        agent = CourseArchitectAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "topic": "Machine Learning",
            "audience": "graduate",
            "duration_weeks": 10,
        }, _persona(), tools)
        for outcome in result["output"]["outcomes"]:
            assert "bloom_level" in outcome
            assert outcome["bloom_level"] in ["remember", "understand", "apply", "analyze", "evaluate", "create"]

    @pytest.mark.asyncio
    async def test_standards_alignment(self):
        agent = CourseArchitectAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "topic": "CS 101",
            "audience": "undergrad",
            "duration_weeks": 15,
            "standards": ["ABET"],
        }, _persona(), tools)
        # First outcome should have the looked-up standard
        assert len(result["output"]["outcomes"][0]["standards"]) > 0

    @pytest.mark.asyncio
    async def test_draft_saved(self):
        agent = CourseArchitectAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "topic": "Biology",
            "audience": "high school",
            "duration_weeks": 18,
        }, _persona(), tools)
        # content.save_draft should have been called
        tool_names = [tc["tool_name"] for tc in result["tool_calls"]]
        assert "content.save_draft" in tool_names

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = CourseArchitectAgent()
        assert "Course Architect" in agent.system_prompt
        assert "user_content" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_module_count_capped(self):
        agent = CourseArchitectAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "topic": "Very Long Course",
            "audience": "undergrad",
            "duration_weeks": 52,
        }, _persona(), tools)
        # Should cap at 12 modules
        assert len(result["output"]["modules"]) == 12
