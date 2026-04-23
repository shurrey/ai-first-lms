"""Agent runner — protocol-based interface for invoking sub-agents."""

from __future__ import annotations

import asyncio
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

_TOOL_USE_ADDENDUM = """

---
IMPORTANT RULES FOR TOOL USE:
- If a tool returns empty results (e.g., {"results": []} or {"evidence": []}), do NOT retry the same tool with different parameters. Accept that there is no data.
- If multiple tools return empty or error results, conclude that this course may not have data set up yet. Tell the user honestly: "It looks like this course doesn't have [assignments/content/etc.] set up yet. You may want to check with your instructor."
- Never make more than 2 attempts at any single tool. If data isn't there, it isn't there.
- Always respond to the user even if you couldn't find data. A helpful "no data found" message is better than silence.

IMPORTANT RULES FOR PERSONA CONTEXT:
- The Person ID in the context header identifies WHO IS ASKING, not who to look up.
- If the persona is "faculty", "advisor", or "admin", do NOT use their Person ID to look up student evidence. Their Person ID is the instructor/advisor/admin — they have no student evidence.
- For faculty asking about class performance: use analytics tools (analytics.query, analytics.trend, analytics.cohort_compare) for course-level metrics. Do NOT iterate over individual students — that is too slow.
- For faculty asking about at-risk students: use analytics.query or analytics.cohort_compare to find outliers. Do NOT fetch evidence for every student one by one.
- For faculty asking about a specific student: ask for the student's name, then look them up via roster tools.
- Only use the Person ID for student-data lookups when the persona is "student".
- NEVER call the same tool more than 5 times in a single turn. If you need data for many students, use analytics tools that aggregate across the course.

IMPORTANT RULES FOR RESPONSE FORMAT:
- Return your response as plain markdown text. Do NOT wrap it in JSON.
- Do NOT append a JSON block with response_markdown, citations, follow_ups, etc.
- If you want to suggest follow-up questions, include them naturally in your response text.
- Your FINAL response must be a complete, user-facing answer — NOT a status update about what you just did or are about to do.
- BAD final response: "Quiz saved. Now saving the study guide."
- GOOD final response: "Here's your recursion quiz with 5 questions covering base cases, recursive thinking, and memoization. I've also created a study guide covering the key concepts."
- If you used tools to create or save something, summarize WHAT you created for the user, don't narrate the process.
"""


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
        "content.retrieve", "content.search", "content.get_skill",
        "roster.get_student_context",
        "assessments.list_recent_evidence",
        "graph.mastery_map", "graph.neighbors", "graph.prerequisites",
        "attestations.get_student_attestations", "attestations.attest",
        "roster.get_learner_profile", "roster.update_learner_profile",
    ],
    "course_architect": [
        "standards.lookup", "content.library_search", "content.save_draft",
        "content.get_skill", "content.save_skill", "content.list_skills",
    ],
    "content_generator": [
        "content.retrieve", "content.search", "content.save_draft",
        "content.get_skill", "content.save_skill", "content.list_skills",
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
        "analytics.query", "analytics.trend", "analytics.cohort_compare",
        "sis.get_transcript", "sis.catalog_search",
        "graph.mastery_map", "attestations.get_student_attestations",
    ],
    "advising": [
        "roster.get_student_context", "roster.get_student",
        "sis.get_transcript", "sis.degree_audit", "sis.catalog_search",
    ],
    "accessibility": [
        "content.retrieve", "content.search",
    ],
    "engagement_analyst": [
        "roster.list_by_course", "assessments.list_recent_evidence",
        "analytics.query", "analytics.trend", "analytics.cohort_compare",
    ],
    "communication": [
        "roster.list_by_course", "roster.get_student_context",
    ],
}


_AGENT_META_KEYS = {"response_markdown", "narrative_md", "citations", "follow_ups", "suggested_nodes", "charts", "caveats", "query_used"}


def _parse_agent_output(text: str) -> dict[str, Any]:
    """Parse agent response text into a structured output dict.

    Strips trailing JSON metadata blocks that agents append after their
    markdown response. Extracts follow_ups and citations from the JSON.
    """
    stripped = text.strip()

    # Case 1: entire response is valid JSON
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict) and _AGENT_META_KEYS & parsed.keys():
            # Normalize: narrative_md → response_markdown
            if "narrative_md" in parsed and "response_markdown" not in parsed:
                parsed["response_markdown"] = parsed.pop("narrative_md")
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Case 2: markdown followed by a JSON block (fenced or bare)
    # Find the last occurrence of a JSON object in the text
    last_brace = stripped.rfind("}")
    if last_brace > 0:
        # Walk backwards to find the matching opening brace
        depth = 0
        start = -1
        for i in range(last_brace, -1, -1):
            if stripped[i] == "}":
                depth += 1
            elif stripped[i] == "{":
                depth -= 1
                if depth == 0:
                    start = i
                    break

        if start > 0:
            json_candidate = stripped[start:last_brace + 1]
            try:
                json_data = json.loads(json_candidate)
                if isinstance(json_data, dict) and _AGENT_META_KEYS & json_data.keys():
                    # Found agent metadata — strip it from the markdown
                    # Also strip any code fence wrapper before the JSON
                    pre = stripped[:start].rstrip()
                    if pre.endswith("```json") or pre.endswith("```"):
                        pre = pre[:pre.rfind("```")].rstrip()

                    # Strip trailing ``` after the JSON
                    post_check = stripped[last_brace + 1:].strip()
                    # pre is the clean markdown

                    md = json_data.get("response_markdown") or json_data.get("narrative_md") or ""
                    # Use the real markdown if response_markdown is a placeholder
                    if not md or md in ("...", "...(above)...", "..."):
                        md = pre

                    result: dict[str, Any] = {"response_markdown": md}
                    for key in ("citations", "follow_ups", "suggested_nodes"):
                        if key in json_data:
                            result[key] = json_data[key]
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

    # Case 3: plain text
    return {"response_markdown": text}


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
        on_event = inputs.pop("_on_event", None)
        logger.info("ClaudeAgentRunner: invoking %s with tools", agent_name)
        start = time.monotonic()

        await _ensure_tool_schemas()
        base_prompt = self._load_system_prompt(agent_name)
        system_prompt = base_prompt + _TOOL_USE_ADDENDUM
        message = inputs.get("message", "")
        persona = inputs.get("persona", "student")
        person_id = inputs.get("person_id", "")
        course_id = inputs.get("course_id", "")
        conversation = inputs.get("conversation", [])

        # Build context prefix — tell the agent who they are and who they're NOT
        persona_note = ""
        if persona in ("advisor", "admin", "faculty"):
            persona_note = (
                f"\nIMPORTANT: Person ID {person_id} is YOUR account (the {persona}), NOT a student. "
                f"Do NOT look up evidence or transcripts for this ID — it will return {persona} data, not student data. "
                f"When asked about a specific student, find their ID first via roster tools, then use THEIR ID."
            )

        if course_id == "all":
            context_prefix = (
                f"[Persona: {persona} | Your ID (do not use for student lookups): {person_id} | Mode: ALL COURSES]"
                f"{persona_note}\n"
                f"You are in cross-course mode. The course_id is 'all', which is NOT a valid UUID.\n"
                f"Do NOT pass 'all' as a course_id to any tool. Instead:\n"
                f"- Use sis.get_transcript(student_id) to get a student's cross-course performance\n"
                f"- Use sis.catalog_search() to discover available courses\n"
                f"- Use roster.list_by_course with specific course UUIDs (discover them first)\n"
                f"- Use assessments.list_recent_evidence(person_id) for a specific student"
            )
        else:
            context_prefix = (
                f"[Persona: {persona} | Your ID (do not use for student lookups): {person_id} | Course ID: {course_id}]"
                f"{persona_note}"
            )

        # Get this agent's allowed tools
        mcp_tool_names = _AGENT_TOOLS.get(agent_name, [])
        claude_tools = _mcp_tools_to_claude_tools(mcp_tool_names)

        # Tool name mapping: Claude uses underscores, MCP uses dots
        tool_name_map = {name.replace(".", "_"): name for name in mcp_tool_names}

        # Build messages with conversation history for context
        messages: list[dict[str, Any]] = []
        if conversation:
            # Add context prefix to the first message
            first_content = conversation[0].get("content", "")
            messages.append({
                "role": conversation[0].get("role", "user"),
                "content": f"{context_prefix}\n\n{first_content}",
            })
            for turn in conversation[1:]:
                messages.append({
                    "role": turn.get("role", "user"),
                    "content": turn.get("content", ""),
                })
            # Add current message
            messages.append({"role": "user", "content": message})
        else:
            messages.append({"role": "user", "content": f"{context_prefix}\n\n{message}"})
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_records: list[dict[str, Any]] = []

        try:
            return await asyncio.wait_for(
                self._tool_loop(agent_name, system_prompt, messages, claude_tools, tool_name_map, tool_call_records, start, on_event),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("Agent %s timed out after %.0fms", agent_name, elapsed_ms)
            return {
                "output": {"response_markdown": "I took too long processing your request. Please try a more specific question."},
                "cost_usd": 0.0,
                "tokens": 0,
                "success": False,
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

    async def _tool_loop(
        self,
        agent_name: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        claude_tools: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        tool_call_records: list[dict[str, Any]],
        start: float,
        on_event: Any = None,
    ) -> dict[str, Any]:
        total_input_tokens = 0
        total_output_tokens = 0

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

                    # Capture any text blocks as thinking/status messages
                    for block in response.content:
                        if block.type == "text" and block.text.strip():
                            record = {
                                "tool": "__thinking__",
                                "arguments": {},
                                "result_summary": block.text.strip()[:200],
                                "latency_ms": 0,
                                "success": True,
                            }
                            tool_call_records.append(record)
                            if on_event:
                                await on_event({"event": "thinking", "payload": {
                                    "step_id": "", "agent": agent_name,
                                    "text": record["result_summary"],
                                }})

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

                            record = {
                                "tool": mcp_name,
                                "arguments": block.input,
                                "result_summary": result_text[:200],
                                "latency_ms": round(tool_ms, 1),
                                "success": "error" not in result_text.lower()[:50],
                            }
                            tool_call_records.append(record)
                            if on_event:
                                await on_event({"event": "agent_tool_call", "payload": {
                                    "step_id": "", "agent": agent_name,
                                    "tool": mcp_name,
                                    "arguments": block.input,
                                    "result_summary": result_text[:200],
                                    "latency_ms": round(tool_ms, 1),
                                    "success": record["success"],
                                }})

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

        output = _parse_agent_output(final_text)

        return {
            "output": output,
            "cost_usd": round(cost_usd, 6),
            "tokens": total_tokens,
            "success": True,
            "tool_calls": tool_call_records,
        }
