"""Tests for the Engagement Analyst agent."""

from __future__ import annotations

import pytest

from src.agents.engagement_analyst.agent import ALLOWED_TOOLS, EngagementAnalystAgent
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {"person_id": "fac-001", "roles": [PersonaRole.faculty], "display_name": "Dr. Torres", "course_id": "cs101"}
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tools():
    async def call(name, args):
        if name == "analytics.describe_schema":
            return {"tables": ["events", "metrics"], "metrics": ["engagement", "completion"]}
        if name == "analytics.query":
            return {"rows": [{"date": "2026-04-01", "value": 0.85}, {"date": "2026-04-08", "value": 0.72}], "metadata": {"query": "SELECT ..."}}
        if name == "charts.render":
            return {"chart_spec": {"type": args.get("type", "bar"), "data": args.get("series", [])}}
        if name == "graph.aggregate":
            return {"value": 0.78, "sample_size": 50, "caveats": []}
        return {}
    return call


class TestEngagementAnalystAgent:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        agent = EngagementAnalystAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({"question": "engagement trends", "scope": {"course_id": "cs101"}}, _persona(), tools)
        assert result["error"] is None
        assert "narrative_md" in result["output"]
        assert len(result["output"]["charts"]) > 0

    @pytest.mark.asyncio
    async def test_chart_type_selection_trend(self):
        agent = EngagementAnalystAgent()
        assert agent._select_chart_type("Show me engagement trends over time") == "line"

    @pytest.mark.asyncio
    async def test_chart_type_selection_comparison(self):
        agent = EngagementAnalystAgent()
        assert agent._select_chart_type("Compare section A vs section B") == "bar"

    @pytest.mark.asyncio
    async def test_small_sample_caveat(self):
        agent = EngagementAnalystAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({"question": "test", "scope": {}}, _persona(), tools)
        caveats = result["output"]["caveats"]
        assert any("Sample size" in c for c in caveats)

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = EngagementAnalystAgent()
        assert "Engagement Analyst" in agent.system_prompt
        assert "user_content" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")
