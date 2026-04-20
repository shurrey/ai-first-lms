"""Tests for the Communication agent."""

from __future__ import annotations

import pytest

from src.agents.communication.agent import ALLOWED_TOOLS, CommunicationAgent
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {"person_id": "fac-001", "roles": [PersonaRole.faculty], "display_name": "Dr. Torres", "course_id": "cs101"}
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tools():
    draft_counter = {"n": 0}
    async def call(name, args):
        if name == "templates.list":
            return {"templates": [{"id": "t-1", "name": "Midterm Reminder", "subject": "Midterm", "body_md": "..."}]}
        if name == "roster.get":
            return {"id": args.get("person_id", ""), "display_name": "Alice Student", "roles": ["student"]}
        if name == "messages.draft":
            draft_counter["n"] += 1
            return {"draft_id": f"draft-{draft_counter['n']}"}
        if name == "messages.send":
            return {"sent_at": "2026-04-20T12:00:00Z", "recipient_count": 1}
        return {}
    return call


class TestCommunicationAgent:
    @pytest.mark.asyncio
    async def test_broadcast_draft(self):
        agent = CommunicationAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "audience": {"course_id": "cs101"},
            "intent": "Midterm on Monday",
            "channel": "announcement",
        }, _persona(), tools)
        assert result["error"] is None
        assert len(result["output"]["drafts"]) >= 1
        assert result["output"]["send_ready_payload"]["channel"] == "announcement"

    @pytest.mark.asyncio
    async def test_personalized_draft(self):
        agent = CommunicationAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "audience": {"student_ids": ["stu-001", "stu-002"]},
            "intent": "Great job on the midterm!",
            "channel": "inbox",
            "tone": "celebratory",
            "personalize": True,
        }, _persona(), tools)
        assert len(result["output"]["drafts"]) == 2
        assert "Alice" in result["output"]["drafts"][0]["body_md"]

    @pytest.mark.asyncio
    async def test_send_ready_payload_has_draft_ids(self):
        agent = CommunicationAgent()
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        result = await agent.run({
            "audience": {"student_ids": ["stu-001"]},
            "intent": "Reminder",
            "channel": "email",
        }, _persona(), tools)
        payload = result["output"]["send_ready_payload"]
        assert len(payload["draft_ids"]) == 1
        assert payload["scheduled_for"] is None

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        agent = CommunicationAgent()
        assert "Communication" in agent.system_prompt
        assert "user_content" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        tools = ToolBag(call_tool=_mock_tools(), allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("analytics.query", scope={}, metric="x", window={})
