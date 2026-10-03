"""Shared MCP server factory for all seven MCP servers."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import structlog
from mcp.server import Server
from mcp.types import TextContent, Tool

from common import clock
from data_mcp.mcp_base.logging import log_tool_call

logger = structlog.get_logger()

ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


@dataclass
class ToolDef:
    """Definition of a single MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    mutates: bool = False
    requires_approval: bool = False


def create_mcp_server(
    server_name: str,
    tools: list[ToolDef],
) -> Server:
    """Create a configured MCP Server with the given tools.

    Each tool call is wrapped with structured logging and error handling. Raises
    ValueError if LMS_AS_OF is set but malformed.
    """
    pinned = clock.as_of()
    if pinned is not None:
        logger.info("mcp_clock_pinned", server=server_name, as_of=pinned.isoformat())
    server = Server(server_name)
    tool_map: dict[str, ToolDef] = {t.name: t for t in tools}

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
            )
            for t in tools
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        if name not in tool_map:
            error_msg = f"Unknown tool: {name}"
            log_tool_call(server_name, name, arguments, None, error=error_msg, latency_ms=0)
            return [TextContent(type="text", text=json.dumps({"error": error_msg}))]

        tool_def = tool_map[name]
        args = arguments or {}
        start = time.monotonic()

        try:
            result = await tool_def.handler(args)
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            log_tool_call(server_name, name, args, result, latency_ms=latency_ms)
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            error_msg = f"{type(exc).__name__}: {exc}"
            log_tool_call(server_name, name, args, None, error=error_msg, latency_ms=latency_ms)
            return [TextContent(type="text", text=json.dumps({"error": error_msg}))]

    return server
