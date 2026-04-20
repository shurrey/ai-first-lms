"""Budget guardrail — per-turn caps on tokens, tool calls, and wall time (SPEC §4.5)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))


@dataclass
class BudgetConfig:
    max_tokens: int = 0
    max_tool_calls: int = 0
    max_wall_time_ms: int = 0
    max_agent_invocations: int = 0

    @classmethod
    def from_env(cls) -> BudgetConfig:
        return cls(
            max_tokens=_env_int("MAX_TOKENS_PER_TURN", 250_000),
            max_tool_calls=_env_int("MAX_TOOL_CALLS_PER_TURN", 40),
            max_wall_time_ms=_env_int("MAX_WALL_TIME_PER_TURN_MS", 120_000),
            max_agent_invocations=_env_int("MAX_AGENT_INVOCATIONS_PER_TURN", 8),
        )


@dataclass
class BudgetExceeded:
    exceeded: bool
    reason: str = ""
    code: str = "budget_exceeded"


class BudgetTracker:
    """Tracks resource usage within a single turn and checks against caps."""

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig.from_env()
        self.tokens_used: int = 0
        self.tool_calls_made: int = 0
        self.agent_invocations: int = 0
        self._start_time: float = time.monotonic()

    def add_tokens(self, count: int) -> None:
        self.tokens_used += count

    def add_tool_call(self) -> None:
        self.tool_calls_made += 1

    def add_agent_invocation(self) -> None:
        self.agent_invocations += 1

    @property
    def wall_time_ms(self) -> float:
        return (time.monotonic() - self._start_time) * 1000

    def check(self) -> BudgetExceeded:
        """Check if any budget cap has been exceeded."""
        if self.tokens_used > self.config.max_tokens:
            return BudgetExceeded(
                exceeded=True,
                reason=f"Token limit exceeded: {self.tokens_used}/{self.config.max_tokens}",
            )
        if self.tool_calls_made > self.config.max_tool_calls:
            return BudgetExceeded(
                exceeded=True,
                reason=f"Tool call limit exceeded: {self.tool_calls_made}/{self.config.max_tool_calls}",
            )
        if self.wall_time_ms > self.config.max_wall_time_ms:
            return BudgetExceeded(
                exceeded=True,
                reason=f"Wall time limit exceeded: {self.wall_time_ms:.0f}ms/{self.config.max_wall_time_ms}ms",
            )
        if self.agent_invocations > self.config.max_agent_invocations:
            return BudgetExceeded(
                exceeded=True,
                reason=f"Agent invocation limit exceeded: {self.agent_invocations}/{self.config.max_agent_invocations}",
            )
        return BudgetExceeded(exceeded=False)

    def summary(self) -> dict[str, float | int]:
        return {
            "tokens_used": self.tokens_used,
            "tool_calls_made": self.tool_calls_made,
            "agent_invocations": self.agent_invocations,
            "wall_time_ms": round(self.wall_time_ms),
        }
