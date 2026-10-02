"""Budget guardrail — per-turn caps on tokens, tool calls, and wall time (SPEC-v1 §4.5).

The ToolGateway is the only caller that halts a turn on an exceeded cap (spec.md §5.2 step 6).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
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


class BudgetExceededError(Exception):  # noqa: N818
    """Raised by the gateway when a charge takes the turn over a cap; the turn hard-stops."""

    code = "budget_exceeded"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # names the cap and the counts; no user content


class ActiveClock:
    """Monotonic elapsed time that excludes spans spent waiting on a person.

    Pauses nest (parallel steps may each wait on an approval); time counts again only
    once every pause has ended. Not thread-safe; one event loop only.
    """

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._depth = 0

    @property
    def paused(self) -> bool:
        return self._depth > 0

    @property
    def elapsed_s(self) -> float:
        now = time.monotonic()
        paused = self._paused_total
        if self._paused_at is not None:
            paused += now - self._paused_at
        return now - self._start - paused

    @contextmanager
    def pause(self) -> Iterator[None]:
        if self._depth == 0:
            self._paused_at = time.monotonic()
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0 and self._paused_at is not None:
                self._paused_total += time.monotonic() - self._paused_at
                self._paused_at = None


class BudgetTracker:
    """Tracks resource usage within a single turn and checks against caps."""

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig.from_env()
        self.tokens_used: int = 0
        self.tool_calls_made: int = 0
        self.agent_invocations: int = 0
        self.clock = ActiveClock()  # wall time excludes time waiting for a human approval

    def charge(
        self, *, tokens: int = 0, tool_calls: int = 0, agent_invocations: int = 0
    ) -> BudgetExceeded:
        """Add usage, then check every cap (wall time included)."""
        self.tokens_used += tokens
        self.tool_calls_made += tool_calls
        self.agent_invocations += agent_invocations
        return self.check()

    @property
    def wall_time_ms(self) -> float:
        return self.clock.elapsed_s * 1000

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
