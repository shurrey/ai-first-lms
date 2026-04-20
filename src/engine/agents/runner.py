"""Agent runner — protocol-based interface for invoking sub-agents."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Protocol

import anthropic
import httpx

logger = logging.getLogger(__name__)

# Map agent names to their source directories (for loading system prompts)
_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"

# MCP server endpoints (container hostnames inside docker network)
_MCP_SERVERS: dict[str, str] = {
    "content": "http://mcp-content:7001",
    "roster": "http://mcp-roster:7002",
    "assessments": "http://mcp-assessments:7003",
    "analytics": "http://mcp-analytics:7004",
    "sis": "http://mcp-sis:7005",
    "communications": "http://mcp-communications:7006",
    "standards": "http://mcp-standards:7007",
    "graph": "http://mcp-content:7001",  # graph tools live on content server
}

# Max tool-use iterations to prevent infinite loops
_MAX_TOOL_ROUNDS = 10


class AgentRunner(Protocol):
    """Protocol for running a sub-agent. Implementations wrap the actual agent SDK."""

    async def run(
        self, agent_name: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Invoke an agent and return its structured output.

        Returns a dict with at minimum:
        - output: dict — the agent's structured output
        - cost_usd: float
        - tokens: int
        - success: bool
        - tool_calls: list[dict] — MCP tool calls made
        """
        ...


class StubAgentRunner:
    """Stub agent runner that returns canned responses. Used until real agents exist."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    async def run(
        self, agent_name: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append({"agent": agent_name, "inputs": inputs})
        logger.info("StubAgentRunner: invoking %s", agent_name)

        if agent_name in self._responses:
            return self._responses[agent_name]

        return {
            "output": {"response_markdown": f"Stub response from {agent_name}"},
            "cost_usd": 0.005,
            "tokens": 500,
            "success": True,
            "tool_calls": [],
        }


async def _call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Call an MCP tool via SSE transport and return the JSON result."""
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    # Parse server from tool name: "content.search" → server="content", tool="content.search"
    server_name = tool_name.split(".")[0]
    base_url = _MCP_SERVERS.get(server_name)
    if not base_url:
        return json.dumps({"error": f"Unknown MCP server for tool: {tool_name}"})

    try:
        async with sse_client(f"{base_url}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # MCP returns a list of content blocks; extract text
                parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                return "\n".join(parts) if parts else json.dumps({"result": "empty"})
    except Exception as exc:
        logger.warning("MCP tool %s failed: %s", tool_name, exc)
        return json.dumps({"error": f"Tool call failed: {exc}"})


# Cached tool schemas fetched from MCP servers at first use
_tool_schema_cache: dict[str, dict[str, Any]] = {}
_schema_cache_loaded = False


async def _ensure_tool_schemas() -> None:
    """Fetch and cache tool schemas from all MCP servers (once)."""
    global _schema_cache_loaded
    if _schema_cache_loaded:
        return

    from mcp.client.sse import sse_client
    from mcp import ClientSession

    for server_name, base_url in _MCP_SERVERS.items():
        if server_name == "graph":  # alias for content
            continue
        try:
            async with sse_client(f"{base_url}/sse") as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    for t in tools_result.tools:
                        _tool_schema_cache[t.name] = {
                            "name": t.name.replace(".", "_"),
                            "description": t.description or f"MCP tool: {t.name}",
                            "input_schema": t.inputSchema,
                        }
            logger.info("Loaded %d tool schemas from %s", len([k for k in _tool_schema_cache if k.startswith(server_name)]), server_name)
        except Exception as exc:
            logger.warning("Failed to load schemas from %s: %s", server_name, exc)

    _schema_cache_loaded = True


def _mcp_tools_to_claude_tools(mcp_tool_names: list[str]) -> list[dict[str, Any]]:
    """Convert MCP tool names to Claude API tool definitions using cached schemas."""
    tools = []
    for name in mcp_tool_names:
        if name in _tool_schema_cache:
            tools.append(_tool_schema_cache[name])
        else:
            # Fallback for tools not in cache
            tools.append({
                "name": name.replace(".", "_"),
                "description": f"MCP tool: {name}",
                "input_schema": {"type": "object", "additionalProperties": True},
            })
    return tools


# Map from agent name → list of MCP tools they can use (from manifests)
_AGENT_TOOLS: dict[str, list[str]] = {
    "tutor": [
        "content.retrieve", "content.search", "roster.get_student_context",
        "assessments.list_recent_evidence",
    ],
    "course_architect": [
        "standards.lookup", "content.library_search", "content.save_draft",
    ],
    "content_generator": [
        "content.retrieve", "content.search", "content.save_draft",
    ],
    "assessment": [
        "assessments.create_question", "assessments.search_bank",
        "assessments.get_rubric", "assessments.list_recent_evidence",
    ],
    "grading_assistant": [
        "assessments.get_submission", "assessments.get_rubric",
        "assessments.draft_grade", "assessments.commit_grade",
    ],
    "early_alert": [
        "roster.get_student_context", "assessments.list_recent_evidence",
        "roster.list_by_course",
    ],
    "advising": [
        "roster.get_student_context", "roster.get_student",
    ],
    "accessibility": [
        "content.retrieve", "content.search",
    ],
    "engagement_analyst": [
        "roster.list_by_course", "assessments.list_recent_evidence",
    ],
    "communication": [
        "roster.list_by_course", "roster.get_student_context",
    ],
}


class ClaudeAgentRunner:
    """Agent runner with full tool-use loop connected to real MCP servers."""

    _AGENT_DIR_MAP: dict[str, str] = {
        "tutor": "tutor",
        "course_architect": "course_architect",
        "content_generator": "content_generator",
        "assessment": "assessment",
        "grading_assistant": "grading_assistant",
        "early_alert": "early_alert",
        "advising": "advising",
        "accessibility": "accessibility",
        "engagement_analyst": "engagement_analyst",
        "communication": "communication",
    }

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.AsyncAnthropic(
            http_client=httpx.AsyncClient(verify=False),
        )
        self._model = model
        self._prompt_cache: dict[str, str] = {}

    def _load_system_prompt(self, agent_name: str) -> str:
        if agent_name in self._prompt_cache:
            return self._prompt_cache[agent_name]

        dir_name = self._AGENT_DIR_MAP.get(agent_name, agent_name)
        prompt_path = _AGENTS_DIR / dir_name / "system_prompt.md"

        if prompt_path.exists():
            prompt = prompt_path.read_text()
        else:
            prompt = f"You are the {agent_name} agent in an AI-native learning management system. Help the user with their request."

        self._prompt_cache[agent_name] = prompt
        return prompt

    async def run(
        self, agent_name: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        logger.info("ClaudeAgentRunner: invoking %s with tools", agent_name)
        start = time.monotonic()

        await _ensure_tool_schemas()
        system_prompt = self._load_system_prompt(agent_name)
        message = inputs.get("message", "")
        persona = inputs.get("persona", "student")
        person_id = inputs.get("person_id", "")
        course_id = inputs.get("course_id", "")

        user_content = f"[Persona: {persona} | Person ID: {person_id} | Course ID: {course_id}]\n\n{message}"

        # Get this agent's allowed tools
        mcp_tool_names = _AGENT_TOOLS.get(agent_name, [])
        claude_tools = _mcp_tools_to_claude_tools(mcp_tool_names)

        # Tool name mapping: Claude uses underscores, MCP uses dots
        tool_name_map = {name.replace(".", "_"): name for name in mcp_tool_names}

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_records: list[dict[str, Any]] = []

        try:
            for _round in range(_MAX_TOOL_ROUNDS):
                response = await self._client.messages.create(
                    model=self._model,
                    system=system_prompt,
                    messages=messages,
                    tools=claude_tools if claude_tools else anthropic.NOT_GIVEN,
                    max_tokens=2048,
                )

                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                # If Claude is done (no tool use), extract final text
                if response.stop_reason == "end_turn":
                    text_parts = [b.text for b in response.content if b.type == "text"]
                    final_text = "\n".join(text_parts)
                    break

                # Handle tool use
                if response.stop_reason == "tool_use":
                    # Add assistant message with all content blocks
                    messages.append({"role": "assistant", "content": response.content})

                    # Execute each tool call
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            mcp_name = tool_name_map.get(block.name, block.name)
                            tool_start = time.monotonic()
                            result_text = await _call_mcp_tool(mcp_name, block.input)
                            tool_ms = (time.monotonic() - tool_start) * 1000

                            logger.info(
                                "Tool %s returned in %.0fms", mcp_name, tool_ms
                            )

                            tool_call_records.append({
                                "tool": mcp_name,
                                "arguments": block.input,
                                "result_summary": result_text[:200],
                                "latency_ms": round(tool_ms, 1),
                                "success": "error" not in result_text.lower()[:50],
                            })

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_text,
                            })

                    messages.append({"role": "user", "content": tool_results})
                    continue

                # Unexpected stop reason — extract what we have
                text_parts = [b.text for b in response.content if b.type == "text"]
                final_text = "\n".join(text_parts) if text_parts else "Agent produced no text response."
                break
            else:
                # Exhausted tool rounds
                final_text = "Agent exceeded maximum tool-use rounds."

            elapsed_ms = (time.monotonic() - start) * 1000
            total_tokens = total_input_tokens + total_output_tokens
            cost_usd = (total_input_tokens * 3.0 / 1_000_000) + (total_output_tokens * 15.0 / 1_000_000)

            logger.info(
                "Agent %s done in %.0fms (%d tokens, %d tool calls, $%.4f)",
                agent_name, elapsed_ms, total_tokens, len(tool_call_records), cost_usd,
            )

            return {
                "output": {"response_markdown": final_text},
                "cost_usd": round(cost_usd, 6),
                "tokens": total_tokens,
                "success": True,
                "tool_calls": tool_call_records,
            }

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception("Agent %s failed after %.0fms: %s", agent_name, elapsed_ms, exc)
            return {
                "output": {"response_markdown": f"Error from {agent_name}: {exc}"},
                "cost_usd": 0.0,
                "tokens": 0,
                "success": False,
                "tool_calls": tool_call_records,
            }
