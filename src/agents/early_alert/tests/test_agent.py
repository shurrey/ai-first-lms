"""Tests for the Early Alert agent."""

from __future__ import annotations

import pytest

from src.agents.early_alert.agent import ALLOWED_TOOLS, EarlyAlertAgent
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
        if name == "roster.get":
            return {
                "students": [
                    {"student_id": "stu-001", "display_name": "Alice"},
                    {"student_id": "stu-002", "display_name": "Bob"},
                    {"student_id": "stu-003", "display_name": "Carol"},
                ]
            }
        if name == "analytics.query":
            return {
                "rows": [
                    {
                        "student_id": "stu-001",
                        "login_ratio": 0.3,
                        "assignment_completion_rate": 0.4,
                        "assignments_missed": 3,
                        "assignments_total": 5,
                        "grade_trend": -0.2,
                    },
                    {
                        "student_id": "stu-002",
                        "login_ratio": 0.9,
                        "assignment_completion_rate": 0.95,
                        "assignments_missed": 0,
                        "assignments_total": 5,
                        "grade_trend": 0.05,
                    },
                    {
                        "student_id": "stu-003",
                        "login_ratio": 0.6,
                        "assignment_completion_rate": 0.7,
                        "assignments_missed": 1,
                        "assignments_total": 5,
                        "grade_trend": -0.1,
                    },
                ]
            }
        if name == "graph.evidence_summary":
            return {
                "summaries": [
                    {"student_id": "stu-001", "stalled_nodes": 3},
                    {"student_id": "stu-002", "stalled_nodes": 0},
                    {"student_id": "stu-003", "stalled_nodes": 1},
                ]
            }
        if name == "interventions.playbook":
            return {
                "interventions": [
                    {
                        "category": "engagement",
                        "strategies": [
                            "Send personalized check-in message",
                            "Schedule one-on-one meeting",
                        ],
                    },
                    {
                        "category": "assignment_completion",
                        "strategies": [
                            "Reach out about missing work",
                            "Offer extended deadline if eligible",
                        ],
                    },
                    {
                        "category": "grade_decline",
                        "strategies": [
                            "Recommend tutoring center",
                            "Review recent assessment feedback",
                        ],
                    },
                    {
                        "category": "mastery_gap",
                        "strategies": [
                            "Recommend prerequisite review materials",
                            "Refer to tutoring center for foundational topics",
                        ],
                    },
                ]
            }
        return {}

    return call


class TestEarlyAlertAgent:
    @pytest.mark.asyncio
    async def test_identifies_at_risk_students(self):
        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"course_id": "cs101"}, "window_days": 14, "risk_threshold": 0.5},
            persona,
            tools,
        )

        assert result["agent_name"] == "early_alert"
        assert result["error"] is None
        out = result["output"]
        at_risk = out["at_risk"]
        # stu-001 (Alice) should definitely be flagged (low login, low completion, declining grade, stalled nodes)
        flagged_ids = [s["student_id"] for s in at_risk]
        assert "stu-001" in flagged_ids
        # stu-002 (Bob) should NOT be flagged (good metrics)
        assert "stu-002" not in flagged_ids

    @pytest.mark.asyncio
    async def test_each_flagged_student_has_factors(self):
        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"course_id": "cs101"}},
            persona,
            tools,
        )

        for entry in result["output"]["at_risk"]:
            assert "factors" in entry
            assert len(entry["factors"]) > 0, (
                f"Student {entry['student_id']} flagged without factors"
            )

    @pytest.mark.asyncio
    async def test_each_flagged_student_has_interventions(self):
        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"course_id": "cs101"}},
            persona,
            tools,
        )

        for entry in result["output"]["at_risk"]:
            assert "recommended_interventions" in entry
            assert len(entry["recommended_interventions"]) > 0, (
                f"Student {entry['student_id']} flagged without interventions"
            )

    @pytest.mark.asyncio
    async def test_methodology_note_present(self):
        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"course_id": "cs101"}},
            persona,
            tools,
        )

        note = result["output"]["methodology_note"]
        assert isinstance(note, str)
        assert len(note) > 0
        assert "14-day" in note
        # Should mention small-N warning for 3 students
        assert "3 student" in note

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = EarlyAlertAgent()
        assert "Early Alert" in agent.system_prompt
        assert "user_content" in agent.system_prompt
        assert "WILL NOT" in agent.system_prompt
        assert "interventions" in agent.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        """Early Alert should not be able to call tools outside its allowed set."""
        async def noop(name, args):
            return {}

        tools = ToolBag(call_tool=noop, allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")

    @pytest.mark.asyncio
    async def test_empty_roster_returns_empty(self):
        """If no students in scope, at_risk should be empty with a note."""

        async def empty_roster(name, args):
            if name == "roster.get":
                return {"students": []}
            return {}

        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=empty_roster, allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"course_id": "empty-course"}},
            persona,
            tools,
        )

        assert result["error"] is None
        assert result["output"]["at_risk"] == []
        assert "No students" in result["output"]["methodology_note"]

    @pytest.mark.asyncio
    async def test_high_threshold_filters_more(self):
        """A higher threshold should flag fewer students."""
        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result_low = await agent.run(
            {"scope": {"course_id": "cs101"}, "risk_threshold": 0.3},
            persona,
            tools,
        )
        result_high = await agent.run(
            {"scope": {"course_id": "cs101"}, "risk_threshold": 0.8},
            persona,
            tools,
        )

        count_low = len(result_low["output"]["at_risk"])
        count_high = len(result_high["output"]["at_risk"])
        assert count_low >= count_high

    @pytest.mark.asyncio
    async def test_results_sorted_by_risk_descending(self):
        agent = EarlyAlertAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"course_id": "cs101"}, "risk_threshold": 0.3},
            persona,
            tools,
        )

        scores = [s["risk_score"] for s in result["output"]["at_risk"]]
        assert scores == sorted(scores, reverse=True)
