"""Tests for the agent base scaffold."""

from __future__ import annotations

import pytest

from src.agents import (
    AgentResult,
    BaseAgent,
    PersonaContext,
    PersonaRole,
    ToolBag,
    ToolCall,
    wrap_fields,
    wrap_user_content,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class EchoAgent(BaseAgent):
    """Minimal agent that echoes its inputs for testing."""

    name = "echo"

    async def _run(self, inputs, persona, tools):
        return {"echo": inputs.get("message", "")}


class ToolUsingAgent(BaseAgent):
    """Agent that calls a tool during _run."""

    name = "tool_user"

    async def _run(self, inputs, persona, tools):
        result = await tools.call("content.retrieve", node_id="abc-123")
        return {"content": result}


class FailingAgent(BaseAgent):
    """Agent that always raises."""

    name = "failing"

    async def _run(self, inputs, persona, tools):
        raise ValueError("something broke")


def _make_persona(**overrides):
    defaults = {
        "person_id": "stu-001",
        "roles": [PersonaRole.student],
        "display_name": "Test Student",
        "course_id": "cs101",
    }
    defaults.update(overrides)
    return PersonaContext(**defaults)


# ---------------------------------------------------------------------------
# PersonaContext
# ---------------------------------------------------------------------------


class TestPersonaContext:
    def test_create_with_required_fields(self):
        p = PersonaContext(person_id="u1", roles=[PersonaRole.faculty])
        assert p.person_id == "u1"
        assert p.display_name == ""
        assert p.course_id is None

    def test_create_with_all_fields(self):
        p = _make_persona()
        assert p.display_name == "Test Student"
        assert p.course_id == "cs101"


# ---------------------------------------------------------------------------
# ToolBag
# ---------------------------------------------------------------------------


class TestToolBag:
    @pytest.mark.asyncio
    async def test_call_logs_success(self):
        async def mock_tool(name, args):
            return {"body_md": "hello"}

        bag = ToolBag(call_tool=mock_tool)
        result = await bag.call("content.retrieve", node_id="x")
        assert result == {"body_md": "hello"}
        assert len(bag.history) == 1
        assert bag.history[0].tool_name == "content.retrieve"
        assert bag.history[0].error is None
        assert bag.history[0].latency_ms > 0

    @pytest.mark.asyncio
    async def test_call_logs_error(self):
        async def failing_tool(name, args):
            raise RuntimeError("boom")

        bag = ToolBag(call_tool=failing_tool)
        with pytest.raises(RuntimeError, match="boom"):
            await bag.call("content.retrieve", node_id="x")
        assert len(bag.history) == 1
        assert bag.history[0].error == "boom"

    @pytest.mark.asyncio
    async def test_allowed_tools_enforced(self):
        async def mock_tool(name, args):
            return {}

        bag = ToolBag(call_tool=mock_tool, allowed_tools=["content.search"])
        with pytest.raises(PermissionError, match="not in this agent's allowed tool set"):
            await bag.call("content.retrieve", node_id="x")

    @pytest.mark.asyncio
    async def test_allowed_tools_permits_valid(self):
        async def mock_tool(name, args):
            return {"ok": True}

        bag = ToolBag(call_tool=mock_tool, allowed_tools=["content.search"])
        result = await bag.call("content.search", query="test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_no_backend_raises(self):
        bag = ToolBag()
        with pytest.raises(RuntimeError, match="No tool backend"):
            await bag.call("content.retrieve", node_id="x")


# ---------------------------------------------------------------------------
# BaseAgent (via EchoAgent, ToolUsingAgent, FailingAgent)
# ---------------------------------------------------------------------------


class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_echo_agent_returns_envelope(self):
        agent = EchoAgent()
        persona = _make_persona()
        tools = ToolBag()
        result = await agent.run({"message": "hello"}, persona, tools)

        assert result["agent_name"] == "echo"
        assert result["output"] == {"echo": "hello"}
        assert result["error"] is None
        assert result["latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_tool_using_agent_records_calls(self):
        async def mock_tool(name, args):
            return {"body_md": "content here"}

        agent = ToolUsingAgent()
        persona = _make_persona()
        tools = ToolBag(call_tool=mock_tool)
        result = await agent.run({}, persona, tools)

        assert result["output"]["content"] == {"body_md": "content here"}
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool_name"] == "content.retrieve"

    @pytest.mark.asyncio
    async def test_failing_agent_captures_error(self):
        agent = FailingAgent()
        persona = _make_persona()
        tools = ToolBag()
        result = await agent.run({}, persona, tools)

        assert result["agent_name"] == "failing"
        assert result["error"] == "something broke"
        assert result["output"] == {}


# ---------------------------------------------------------------------------
# Safety utilities
# ---------------------------------------------------------------------------


class TestSafety:
    def test_wrap_user_content(self):
        wrapped = wrap_user_content("Hello world")
        assert wrapped == "<user_content>Hello world</user_content>"

    def test_wrap_user_content_empty(self):
        wrapped = wrap_user_content("")
        assert wrapped == "<user_content></user_content>"

    def test_wrap_fields_selective(self):
        record = {"title": "Recursion", "body_md": "# Recursion\nBase case...", "score": 0.95}
        wrapped = wrap_fields(record, ["body_md"])
        assert wrapped["title"] == "Recursion"  # untouched
        assert wrapped["body_md"] == "<user_content># Recursion\nBase case...</user_content>"
        assert wrapped["score"] == 0.95  # untouched

    def test_wrap_fields_skips_non_string(self):
        record = {"count": 42}
        wrapped = wrap_fields(record, ["count"])
        assert wrapped["count"] == 42  # not wrapped because not a string

    def test_wrap_fields_missing_key(self):
        record = {"a": "hello"}
        wrapped = wrap_fields(record, ["b"])
        assert wrapped == {"a": "hello"}  # no error, key just absent


# ---------------------------------------------------------------------------
# AgentResult model
# ---------------------------------------------------------------------------


class TestAgentResult:
    def test_defaults(self):
        r = AgentResult(agent_name="test")
        assert r.output == {}
        assert r.tool_calls == []
        assert r.error is None
        assert r.tokens_used == 0
        assert r.latency_ms == 0.0

    def test_round_trip(self):
        r = AgentResult(
            agent_name="tutor",
            output={"response_markdown": "hello"},
            tokens_used=150,
        )
        d = r.model_dump()
        r2 = AgentResult.model_validate(d)
        assert r2.agent_name == "tutor"
        assert r2.output["response_markdown"] == "hello"
