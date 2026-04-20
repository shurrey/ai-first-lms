"""Structured logging for MCP tool calls."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog

logger = structlog.get_logger()


def log_tool_call(
    server: str,
    tool: str,
    args: dict[str, Any] | None,
    result: Any,
    *,
    error: str | None = None,
    latency_ms: float = 0,
) -> None:
    """Emit a structured log record for an MCP tool call."""
    args_digest = hashlib.sha256(
        json.dumps(args or {}, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]

    logger.info(
        "mcp.tool_call",
        server=server,
        tool=tool,
        args_digest=args_digest,
        latency_ms=latency_ms,
        success=error is None,
        error=error,
    )
