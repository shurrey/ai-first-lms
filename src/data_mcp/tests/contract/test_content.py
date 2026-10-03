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


_TIED_LOW = uuid.UUID("00000000-0000-4000-8000-000000000001")
_TIED_HIGH = uuid.UUID("ffffffff-ffff-4fff-bfff-ffffffffffff")


@pytest_asyncio.fixture(loop_scope="module")
async def tied_node(pool):
    """A module whose two content items share created_at, as every seeded item does.
    The lower id is inserted first, which is the row an untied sort happens to return."""
    node = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO nodes (id, kind, title) VALUES ($1, 'module', 'tie')", node)
        for cid in (_TIED_LOW, _TIED_HIGH):
            await conn.execute(
                """INSERT INTO content_items (id, node_id, kind, title, body_md, created_at)
                   VALUES ($1, $2, 'document', $3, '# Tie', '2026-09-01T00:00:00Z')""",
                cid, node, str(cid),
            )
    yield str(node)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM content_items WHERE node_id = $1", node)
        await conn.execute("DELETE FROM nodes WHERE id = $1", node)


async def test_content_retrieve_by_node_breaks_created_at_ties_by_id(server, tied_node) -> None:
    result = await _call(server, "content.retrieve", {"node_id": tied_node})
    assert result["id"] == str(_TIED_HIGH)


async def test_content_search_keyword_matches_are_ordered_by_title(server, pool) -> None:
    node = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO nodes (id, kind, title) VALUES ($1, 'module', 'order')", node)
        for title in ("Zeta qxsearchorder", "Alpha qxsearchorder", "Mid qxsearchorder"):
            await conn.execute(
                """INSERT INTO content_items (node_id, kind, title, body_md)
                   VALUES ($1, 'document', $2, 'body')""",
                node, title,
            )
    try:
        result = await _call(server, "content.search", {"query": "qxsearchorder", "top_k": 2})
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM content_items WHERE node_id = $1", node)
            await conn.execute("DELETE FROM nodes WHERE id = $1", node)
    assert [r["title"] for r in result["results"]] == ["Alpha qxsearchorder", "Mid qxsearchorder"]


async def test_content_search_semantic_ties_are_ordered_by_title(server, pool) -> None:
    # Every item of a module shares the module node's embedding, so their distances tie.
    from data_mcp.embeddings.pipeline import embed_text

    node, course = uuid.uuid4(), str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, metadata, embedding)
               VALUES ($1, 'module', 'semtie', jsonb_build_object('course_id', $2::text),
                       $3::vector)""",
            node, course, str(embed_text("qxsemtie")))
        for title in ("Zeta", "Mid", "Alpha"):
            await conn.execute(
                """INSERT INTO content_items (node_id, kind, title, body_md)
                   VALUES ($1, 'document', $2, 'body')""",
                node, title,
            )
    try:
        result = await _call(server, "content.search",
                             {"query": "qxsemtie", "course_id": course, "top_k": 2})
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM content_items WHERE node_id = $1", node)
            await conn.execute("DELETE FROM nodes WHERE id = $1", node)
    assert [r["title"] for r in result["results"]] == ["Alpha", "Mid"]
