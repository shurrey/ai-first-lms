"""Abstract base class for all sub-agents."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from .types import AgentResult, PersonaContext, ToolBag


class BaseAgent(ABC):
    """Every sub-agent inherits from this class.

    Subclasses implement ``_run`` with their domain logic.  The public
    ``run`` method handles timing, error capture, and result envelope
    construction so each agent doesn't have to.
    """

    name: str = "base"

    async def run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        """Invoke the agent and return a structured result dict."""
        start = time.monotonic()
        try:
            output = await self._run(inputs, persona, tools)
            result = AgentResult(
                agent_name=self.name,
                output=output,
                tool_calls=list(tools.history),
            )
        except Exception as exc:
            result = AgentResult(
                agent_name=self.name,
                error=str(exc),
                tool_calls=list(tools.history),
            )
        result.latency_ms = (time.monotonic() - start) * 1000
        return result.model_dump()

    @abstractmethod
    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        """Implement the agent's core logic. Return the output dict."""
        ...
