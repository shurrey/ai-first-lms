"""Tests for the MCP server scaffold."""
from __future__ import annotations

import json

import pytest
from mcp.types import CallToolRequest, ListToolsRequest

from data_mcp.mcp_base.server import ToolDef, create_mcp_server


async def _mock_echo(args: dict) -> dict:
    return {"echo": args.get("message", "")}


async def _mock_error(args: dict) -> dict:
    raise ValueError("deliberate test error")


@pytest.fixture
def server():
    tools = [
        ToolDef(
            name="test.echo",
            description="Echoes input",
            input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
            handler=_mock_echo,
        ),
        ToolDef(
            name="test.fail",
            description="Always fails",
            input_schema={"type": "object"},
            handler=_mock_error,
        ),
    ]
    return create_mcp_server("test", tools)


@pytest.mark.asyncio
async def test_list_tools(server) -> None:
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    tools = result.root.tools
    assert len(tools) == 2
    assert tools[0].name == "test.echo"
    assert tools[1].name == "test.fail"


@pytest.mark.asyncio
async def test_call_tool_success(server) -> None:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": "test.echo", "arguments": {"message": "hello"}})
    )
    content = result.root.content
    assert len(content) == 1
    data = json.loads(content[0].text)
    assert data == {"echo": "hello"}


@pytest.mark.asyncio
async def test_call_tool_error(server) -> None:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": "test.fail", "arguments": {}})
    )
    content = result.root.content
    assert len(content) == 1
    data = json.loads(content[0].text)
    assert "error" in data
    assert "deliberate test error" in data["error"]


@pytest.mark.asyncio
async def test_call_unknown_tool(server) -> None:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": "nonexistent", "arguments": {}})
    )
    content = result.root.content
    assert len(content) == 1
    data = json.loads(content[0].text)
    assert "error" in data
    assert "Unknown tool" in data["error"]
