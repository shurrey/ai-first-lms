"""Contract tests for the content MCP server tools."""
from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.content.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("content", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    """Get IDs from the seeded CS 101 data."""
    async with pool.acquire() as conn:
        course = await conn.fetchrow("SELECT course_id FROM courses LIMIT 1")
        module = await conn.fetchrow("SELECT module_id FROM modules LIMIT 1")
        content = await conn.fetchrow("SELECT id, node_id FROM content_items LIMIT 1")
        faculty = await conn.fetchrow("SELECT id FROM persons WHERE roles @> '{faculty}' LIMIT 1")
    return {
        "course_id": str(course["course_id"]) if course else None,
        "module_id": str(module["module_id"]) if module else None,
        "content_id": str(content["id"]) if content else None,
        "content_node_id": str(content["node_id"]) if content and content["node_id"] else None,
        "faculty_id": str(faculty["id"]) if faculty else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


async def test_content_retrieve_by_content_id(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "content.retrieve", {"content_id": seeded_ids["content_id"]})
    assert "id" in result
    assert "title" in result
    assert "body_md" in result


async def test_content_retrieve_by_node_id(server, seeded_ids) -> None:
    if not seeded_ids["content_node_id"]:
        pytest.skip("No seeded content with node_id")
    result = await _call(server, "content.retrieve", {"node_id": seeded_ids["content_node_id"]})
    assert "id" in result
    assert "title" in result


async def test_content_retrieve_not_found(server) -> None:
    result = await _call(server, "content.retrieve", {"content_id": str(uuid.uuid4())})
    assert "error" in result


async def test_content_search(server) -> None:
    result = await _call(server, "content.search", {"query": "Variables", "top_k": 5})
    assert "results" in result
    assert isinstance(result["results"], list)


async def test_content_save_draft(server, seeded_ids) -> None:
    result = await _call(server, "content.save_draft", {
        "kind": "document",
        "title": "Test Draft",
        "body_md": "# Test\n\nThis is a test draft.",
        "author_id": seeded_ids["faculty_id"],
    })
    assert "draft_id" in result


async def test_content_library_search(server) -> None:
    result = await _call(server, "content.library_search", {"query": "Control", "top_k": 5})
    assert "items" in result
    assert isinstance(result["items"], list)


async def test_content_library_search_by_kind(server) -> None:
    result = await _call(server, "content.library_search", {"query": "", "kind": "document", "top_k": 5})
    assert "items" in result


async def test_content_list_modules(server, seeded_ids) -> None:
    if not seeded_ids["course_id"]:
        pytest.skip("No seeded course")
    result = await _call(server, "content.list_modules", {"course_id": seeded_ids["course_id"]})
    assert "modules" in result
    assert len(result["modules"]) == 12
    # Verify ordering
    orders = [m["order"] for m in result["modules"]]
    assert orders == sorted(orders)
