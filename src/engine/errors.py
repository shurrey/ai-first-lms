"""Error handling and error event emission per contracts/events.md."""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

ErrorCode = Literal[
    "budget_exceeded", "permission_denied", "agent_failure",
    "mcp_failure", "llm_failure", "timeout", "internal",
]


class EngineError(Exception):
    """Base exception for engine errors with structured metadata."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retriable: bool = False,
        step_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retriable = retriable
        self.step_id = step_id

    def to_event_payload(self) -> dict[str, Any]:
        """Convert to error event payload per contracts/events.md."""
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
        }
        if self.step_id:
            payload["step_id"] = self.step_id
        return payload


class AgentError(EngineError):
    """Error during agent invocation."""

    def __init__(self, agent_name: str, message: str, step_id: str | None = None) -> None:
        super().__init__(
            code="agent_failure",
            message=f"Agent '{agent_name}' failed: {message}",
            retriable=True,
            step_id=step_id,
        )
        self.agent_name = agent_name


class MCPError(EngineError):
    """Error during MCP tool call."""

    def __init__(self, tool_name: str, message: str, step_id: str | None = None) -> None:
        super().__init__(
            code="mcp_failure",
            message=f"MCP tool '{tool_name}' failed: {message}",
            retriable=True,
            step_id=step_id,
        )
        self.tool_name = tool_name


class LLMError(EngineError):
    """Error during LLM call."""

    def __init__(self, message: str, step_id: str | None = None) -> None:
        super().__init__(
            code="llm_failure",
            message=f"LLM call failed: {message}",
            retriable=True,
            step_id=step_id,
        )


class BudgetExceededError(EngineError):
    """Budget cap exceeded."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            code="budget_exceeded",
            message=f"Budget exceeded: {detail}",
            retriable=False,
        )


class PermissionDeniedError(EngineError):
    """Persona lacks permission for an action."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            code="permission_denied",
            message=detail,
            retriable=False,
        )


class TimeoutError(EngineError):
    """Turn exceeded wall time limit."""

    def __init__(self, detail: str, step_id: str | None = None) -> None:
        super().__init__(
            code="timeout",
            message=detail,
            retriable=True,
            step_id=step_id,
        )


def make_error_event(error: EngineError | Exception) -> dict[str, Any]:
    """Create an error event dict from any exception.

    For EngineError subclasses, uses structured metadata.
    For other exceptions, wraps as an internal error (no raw traceback exposed).
    """
    if isinstance(error, EngineError):
        logger.error(
            "Engine error: code=%s message=%s step=%s",
            error.code,
            error.message,
            error.step_id,
        )
        return {
            "event": "error",
            "payload": error.to_event_payload(),
        }

    # Generic exception — wrap as internal, don't leak details
    logger.exception("Unexpected error: %s", error)
    return {
        "event": "error",
        "payload": {
            "code": "internal",
            "message": "An internal error occurred. Please try again.",
            "retriable": True,
        },
    }
