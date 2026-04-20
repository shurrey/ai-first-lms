"""Core types shared across all sub-agents."""

from __future__ import annotations

import time
import uuid
from abc import abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PersonaRole(str, Enum):
    """Roles a person can hold in the system."""

    student = "student"
    faculty = "faculty"
    advisor = "advisor"
    admin = "admin"
    instructional_designer = "instructional_designer"


class PersonaContext(BaseModel):
    """Identity and permissions of the user driving this agent invocation."""

    person_id: str = Field(description="UUID of the person")
    roles: list[PersonaRole] = Field(description="Active roles for this session")
    display_name: str = Field(default="", description="Human-readable name")
    course_id: str | None = Field(default=None, description="Course scope, if any")


class ToolCall(BaseModel):
    """Record of a single MCP tool invocation."""

    tool_name: str
    args: dict[str, Any]
    result: Any = None
    error: str | None = None
    latency_ms: float = 0.0


class ToolBag:
    """Routes MCP tool calls and logs every invocation.

    In production, the Agent SDK wires this to real MCP servers.
    For testing, inject a mock call_tool function.
    """

    def __init__(self, call_tool: Any = None, allowed_tools: list[str] | None = None) -> None:
        self._call_tool = call_tool
        self._allowed_tools: set[str] | None = set(allowed_tools) if allowed_tools else None
        self.history: list[ToolCall] = []

    async def call(self, tool_name: str, **kwargs: Any) -> Any:
        """Invoke an MCP tool by name, logging the call."""
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            raise PermissionError(
                f"Tool '{tool_name}' is not in this agent's allowed tool set"
            )

        record = ToolCall(tool_name=tool_name, args=kwargs)
        start = time.monotonic()
        try:
            if self._call_tool is None:
                raise RuntimeError("No tool backend configured")
            result = await self._call_tool(tool_name, kwargs)
            record.result = result
            return result
        except Exception as exc:
            record.error = str(exc)
            raise
        finally:
            record.latency_ms = (time.monotonic() - start) * 1000
            self.history.append(record)


class AgentResult(BaseModel):
    """Structured envelope every agent returns to the orchestrator."""

    agent_name: str
    output: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    error: str | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
