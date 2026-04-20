"""Agent runner — protocol-based interface for invoking sub-agents."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Protocol

import anthropic
import httpx

logger = logging.getLogger(__name__)

# Map agent names to their source directories (for loading system prompts)
_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


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


class ClaudeAgentRunner:
    """Agent runner that calls Claude API with each agent's system prompt."""

    # Map from dispatch agent names to source directory names
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
        """Load the system prompt for an agent, with caching."""
        if agent_name in self._prompt_cache:
            return self._prompt_cache[agent_name]

        dir_name = self._AGENT_DIR_MAP.get(agent_name, agent_name)
        prompt_path = _AGENTS_DIR / dir_name / "system_prompt.md"

        if prompt_path.exists():
            prompt = prompt_path.read_text()
        else:
            logger.warning("No system prompt found for %s at %s", agent_name, prompt_path)
            prompt = f"You are the {agent_name} agent in an AI-native learning management system. Help the user with their request."

        self._prompt_cache[agent_name] = prompt
        return prompt

    async def run(
        self, agent_name: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        logger.info("ClaudeAgentRunner: invoking %s", agent_name)
        start = time.monotonic()

        system_prompt = self._load_system_prompt(agent_name)
        message = inputs.get("message", "")
        persona = inputs.get("persona", "student")
        course_id = inputs.get("course_id", "")

        # Add session context to the user message
        user_content = f"[Persona: {persona} | Course: {course_id}]\n\n{message}"

        try:
            response = await self._client.messages.create(
                model=self._model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                max_tokens=1024,
            )

            elapsed_ms = (time.monotonic() - start) * 1000
            response_text = response.content[0].text
            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            total_tokens = input_tokens + output_tokens

            # Rough cost estimate (Sonnet pricing)
            cost_usd = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

            logger.info(
                "Agent %s responded in %.0fms (%d tokens, $%.4f)",
                agent_name, elapsed_ms, total_tokens, cost_usd,
            )

            return {
                "output": {"response_markdown": response_text},
                "cost_usd": round(cost_usd, 6),
                "tokens": total_tokens,
                "success": True,
                "tool_calls": [],
            }

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception("Agent %s failed after %.0fms: %s", agent_name, elapsed_ms, exc)
            return {
                "output": {"response_markdown": f"Error from {agent_name}: {exc}"},
                "cost_usd": 0.0,
                "tokens": 0,
                "success": False,
                "tool_calls": [],
            }
