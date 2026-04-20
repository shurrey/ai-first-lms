"""Agent runner — protocol-based interface for invoking sub-agents."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


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
