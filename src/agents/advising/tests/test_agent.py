"""Tests for the Advising agent."""

from __future__ import annotations

import pytest

from src.agents.advising.agent import ALLOWED_TOOLS, AdvisingAgent
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {
        "person_id": "stu-100",
        "roles": [PersonaRole.student],
        "display_name": "Bob Smith",
        "course_id": None,
    }
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tool_backend():
    """Return a mock tool callable that returns canned responses."""

    async def call(name: str, args: dict):
        if name == "sis.degree_audit":
            return {
                "completed": [
                    {"course_id": "CS101", "title": "Intro to CS", "credits": 3},
                    {"course_id": "MATH101", "title": "Calculus I", "credits": 4},
                ],
                "in_progress": [
                    {"course_id": "CS201", "title": "Data Structures", "credits": 3},
                ],
                "remaining": [
                    {
                        "course_id": "CS301",
                        "title": "Algorithms",
                        "credits": 3,
                        "priority": "required",
                    },
                    {
                        "course_id": "CS302",
                        "title": "Operating Systems",
                        "credits": 3,
                        "priority": "required",
                    },
                    {
                        "course_id": "CS401",
                        "title": "Senior Capstone",
                        "credits": 3,
                        "priority": "required",
                    },
                ],
                "total_credits_earned": 10,
                "total_credits_required": 120,
            }
        if name == "sis.get_transcript":
            return {
                "courses": [
                    {"course_id": "CS101", "grade": "A", "credits": 3, "term": "Fall 2024"},
                    {"course_id": "MATH101", "grade": "B+", "credits": 4, "term": "Fall 2024"},
                ]
            }
        if name == "sis.check_prerequisites":
            course_id = args.get("course_id", "")
            if course_id == "CS401":
                return {"met": False, "missing": ["CS301", "CS302"]}
            return {"met": True, "missing": []}
        if name == "catalog.search":
            return {
                "results": [
                    {
                        "title": "Data Science Minor",
                        "required_courses": ["STAT201", "CS350", "CS360"],
                        "additional_credits": 9,
                        "time_delta": "+1 semester",
                    }
                ]
            }
        if name == "schedule.availability":
            course_id = args.get("course_id", "")
            if course_id == "CS302":
                return {"available": False, "term": "next"}
            return {"available": True, "term": "next", "sections": ["A", "B"]}
        if name == "graph.path_to_mastery":
            return {
                "path": [
                    {
                        "node_id": "node-algorithms",
                        "title": "Algorithm Design",
                        "mastery_level": "emerging",
                        "confidence": 0.4,
                    },
                    {
                        "node_id": "node-complexity",
                        "title": "Complexity Analysis",
                        "mastery_level": "not_started",
                        "confidence": 0.0,
                    },
                ]
            }
        return {}

    return call


class TestAdvisingAgent:
    @pytest.mark.asyncio
    async def test_next_term_recommendations(self):
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"student_id": "stu-100", "intent": "next_term"},
            persona,
            tools,
        )

        assert result["agent_name"] == "advising"
        assert result["error"] is None
        out = result["output"]
        assert "audit" in out
        assert "recommendations" in out
        # CS301 should be recommended (prereqs met, available)
        rec_ids = [r["course_id"] for r in out["recommendations"]]
        assert "CS301" in rec_ids
        # CS401 should NOT be recommended (prereqs not met)
        assert "CS401" not in rec_ids

    @pytest.mark.asyncio
    async def test_next_term_flags_missing_prerequisites(self):
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"student_id": "stu-100", "intent": "next_term"},
            persona,
            tools,
        )

        risks = result["output"]["risks"]
        prereq_risks = [r for r in risks if r["type"] == "missing_prerequisite"]
        assert len(prereq_risks) >= 1
        # CS401 should be flagged
        assert any("CS401" in r["description"] for r in prereq_risks)

    @pytest.mark.asyncio
    async def test_degree_plan_intent(self):
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"student_id": "stu-100", "intent": "degree_plan"},
            persona,
            tools,
        )

        assert result["error"] is None
        out = result["output"]
        assert len(out["recommendations"]) == 3  # all remaining courses
        # Should flag CS401 prereqs
        risks = out["risks"]
        assert any("CS401" in r["description"] for r in risks)

    @pytest.mark.asyncio
    async def test_pathway_explore_intent(self):
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "student_id": "stu-100",
                "intent": "pathway_explore",
                "constraints": {"target": "data science minor"},
            },
            persona,
            tools,
        )

        assert result["error"] is None
        out = result["output"]
        assert len(out["alternatives"]) >= 1
        assert "Data Science" in out["alternatives"][0]["scenario"]

    @pytest.mark.asyncio
    async def test_learning_path_intent(self):
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "student_id": "stu-100",
                "intent": "learning_path",
                "constraints": {"target_node": "node-algorithms"},
            },
            persona,
            tools,
        )

        assert result["error"] is None
        out = result["output"]
        assert "path_visualization" in out
        assert len(out["recommendations"]) >= 1
        rec_ids = [r["course_id"] for r in out["recommendations"]]
        assert "node-algorithms" in rec_ids

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = AdvisingAgent()
        assert "Advising" in agent.system_prompt
        assert "user_content" in agent.system_prompt
        assert "prerequisite" in agent.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        """Advising should not be able to call tools outside its allowed set."""

        async def noop_tool(name, args):
            return {}

        tools = ToolBag(call_tool=noop_tool, allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")

    @pytest.mark.asyncio
    async def test_unknown_intent_raises(self):
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"student_id": "stu-100", "intent": "invalid_intent"},
            persona,
            tools,
        )

        assert result["error"] is not None
        assert "Unknown intent" in result["error"]

    @pytest.mark.asyncio
    async def test_unavailable_course_not_recommended(self):
        """CS302 is not available next term, so it should not appear in recommendations."""
        agent = AdvisingAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"student_id": "stu-100", "intent": "next_term"},
            persona,
            tools,
        )

        rec_ids = [r["course_id"] for r in result["output"]["recommendations"]]
        assert "CS302" not in rec_ids
