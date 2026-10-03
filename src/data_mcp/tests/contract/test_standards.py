"""Contract tests for the standards MCP server tools."""
from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.standards.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("standards", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    """Get IDs from the seeded CS 101 data."""
    async with pool.acquire() as conn:
        framework = await conn.fetchrow(
            "SELECT id, name FROM standards_frameworks LIMIT 1"
        )
        standard = await conn.fetchrow(
            "SELECT id, code, framework_id FROM standards LIMIT 1"
        )
        content = await conn.fetchrow(
            "SELECT id, node_id FROM content_items LIMIT 1"
        )
        node = await conn.fetchrow("SELECT id FROM nodes LIMIT 1")
        bloom = await conn.fetchrow(
            "SELECT id, name FROM standards_frameworks WHERE name = 'BLOOM'"
        )
        wcag = await conn.fetchrow(
            "SELECT id, name FROM standards_frameworks WHERE name = 'WCAG_2_1'"
        )
    return {
        "framework_name": framework["name"] if framework else None,
        "framework_id": str(framework["id"]) if framework else None,
        "standard_code": standard["code"] if standard else None,
        "content_id": str(content["id"]) if content else None,
        "content_node_id": str(content["node_id"]) if content and content["node_id"] else None,
        "node_id": str(node["id"]) if node else None,
        "bloom_name": bloom["name"] if bloom else None,
        "wcag_name": wcag["name"] if wcag else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


# ── standards.list_frameworks ────────────────────────────────────────────────

async def test_list_frameworks_returns_list(server) -> None:
    result = await _call(server, "standards.list_frameworks", {})
    assert "frameworks" in result
    assert isinstance(result["frameworks"], list)


async def test_list_frameworks_has_seeded_data(server, seeded_ids) -> None:
    if not seeded_ids["framework_name"]:
        pytest.skip("No seeded frameworks")
    result = await _call(server, "standards.list_frameworks", {})
    names = [f["name"] for f in result["frameworks"]]
    assert seeded_ids["framework_name"] in names


async def test_list_frameworks_has_required_fields(server) -> None:
    result = await _call(server, "standards.list_frameworks", {})
    if not result["frameworks"]:
        pytest.skip("No seeded frameworks")
    fw = result["frameworks"][0]
    assert "id" in fw
    assert "name" in fw
    assert "version" in fw


async def test_list_frameworks_includes_bloom(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.list_frameworks", {})
    names = [f["name"] for f in result["frameworks"]]
    assert "BLOOM" in names


async def test_list_frameworks_includes_wcag(server, seeded_ids) -> None:
    if not seeded_ids["wcag_name"]:
        pytest.skip("WCAG_2_1 framework not seeded")
    result = await _call(server, "standards.list_frameworks", {})
    names = [f["name"] for f in result["frameworks"]]
    assert "WCAG_2_1" in names


# ── standards.lookup ─────────────────────────────────────────────────────────

async def test_lookup_by_framework(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.lookup", {"framework": "BLOOM"})
    assert "standards" in result
    assert isinstance(result["standards"], list)
    assert len(result["standards"]) == 6  # BLOOM has 6 levels seeded


async def test_lookup_by_framework_and_code(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.lookup", {"framework": "BLOOM", "code": "1"})
    assert "standards" in result
    assert len(result["standards"]) == 1
    assert result["standards"][0]["code"] == "1"
    assert result["standards"][0]["title"] == "Remember"


async def test_lookup_by_query(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.lookup", {"framework": "BLOOM", "query": "Apply"})
    assert "standards" in result
    assert any(s["title"] == "Apply" for s in result["standards"])


async def test_lookup_missing_framework_returns_error(server) -> None:
    result = await _call(server, "standards.lookup", {})
    assert "error" in result


async def test_lookup_unknown_framework_returns_error(server) -> None:
    result = await _call(server, "standards.lookup", {"framework": "NONEXISTENT_FW_XYZ"})
    assert "error" in result


async def test_lookup_returns_standard_fields(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.lookup", {"framework": "BLOOM"})
    if not result["standards"]:
        pytest.skip("No standards returned")
    s = result["standards"][0]
    assert "id" in s
    assert "code" in s
    assert "title" in s
    assert "framework" in s
    assert s["framework"] == "BLOOM"


async def test_lookup_wcag_framework(server, seeded_ids) -> None:
    if not seeded_ids["wcag_name"]:
        pytest.skip("WCAG_2_1 framework not seeded")
    result = await _call(server, "standards.lookup", {"framework": "WCAG_2_1"})
    assert "standards" in result


# ── standards.align ──────────────────────────────────────────────────────────

async def test_align_returns_alignments(server, seeded_ids) -> None:
    if not seeded_ids["node_id"] or not seeded_ids["bloom_name"]:
        pytest.skip("No seeded nodes or BLOOM framework")
    result = await _call(server, "standards.align", {
        "node_ids": [seeded_ids["node_id"]],
        "framework": "BLOOM",
    })
    assert "alignments" in result
    assert isinstance(result["alignments"], list)
    assert len(result["alignments"]) == 1
    assert result["alignments"][0]["node_id"] == seeded_ids["node_id"]
    assert "standards" in result["alignments"][0]


async def test_align_multiple_nodes(server, seeded_ids) -> None:
    if not seeded_ids["node_id"] or not seeded_ids["bloom_name"]:
        pytest.skip("No seeded nodes or BLOOM framework")
    # Use same node twice to simulate multiple
    result = await _call(server, "standards.align", {
        "node_ids": [seeded_ids["node_id"], seeded_ids["node_id"]],
        "framework": "BLOOM",
    })
    assert "alignments" in result
    assert len(result["alignments"]) == 2


async def test_align_missing_node_ids_returns_error(server) -> None:
    result = await _call(server, "standards.align", {"framework": "BLOOM"})
    assert "error" in result


async def test_align_missing_framework_returns_error(server, seeded_ids) -> None:
    if not seeded_ids["node_id"]:
        pytest.skip("No seeded nodes")
    result = await _call(server, "standards.align", {"node_ids": [seeded_ids["node_id"]]})
    assert "error" in result


async def test_align_unknown_framework_returns_error(server, seeded_ids) -> None:
    if not seeded_ids["node_id"]:
        pytest.skip("No seeded nodes")
    result = await _call(server, "standards.align", {
        "node_ids": [seeded_ids["node_id"]],
        "framework": "NONEXISTENT_FW_XYZ",
    })
    assert "error" in result


async def test_align_invalid_node_id(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.align", {
        "node_ids": ["not-a-uuid"],
        "framework": "BLOOM",
    })
    assert "alignments" in result
    assert "error" in result["alignments"][0]


async def test_align_nonexistent_node(server, seeded_ids) -> None:
    if not seeded_ids["bloom_name"]:
        pytest.skip("BLOOM framework not seeded")
    result = await _call(server, "standards.align", {
        "node_ids": [str(uuid.uuid4())],
        "framework": "BLOOM",
    })
    assert "alignments" in result
    assert result["alignments"][0]["standards"] == []


# ── standards.check_wcag ─────────────────────────────────────────────────────

async def test_check_wcag_by_content_id(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "standards.check_wcag", {
        "content_id": seeded_ids["content_id"],
        "level": "AA",
    })
    assert "compliant" in result
    assert isinstance(result["compliant"], bool)
    assert "findings" in result
    assert isinstance(result["findings"], list)


async def test_check_wcag_by_node_id(server, seeded_ids) -> None:
    if not seeded_ids["content_node_id"]:
        pytest.skip("No seeded content with node_id")
    result = await _call(server, "standards.check_wcag", {
        "node_id": seeded_ids["content_node_id"],
        "level": "A",
    })
    assert "compliant" in result
    assert "findings" in result


async def test_check_wcag_findings_have_required_fields(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "standards.check_wcag", {
        "content_id": seeded_ids["content_id"],
        "level": "AA",
    })
    assert result["findings"]
    for finding in result["findings"]:
        assert "criterion" in finding
        assert "status" in finding
        assert "details" in finding
        assert finding["status"] in ("pass", "fail", "not_applicable")


async def test_check_wcag_level_a(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "standards.check_wcag", {
        "content_id": seeded_ids["content_id"],
        "level": "A",
    })
    assert "compliant" in result
    assert result["level"] == "A"


async def test_check_wcag_level_aaa(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "standards.check_wcag", {
        "content_id": seeded_ids["content_id"],
        "level": "AAA",
    })
    assert "compliant" in result
    assert result["level"] == "AAA"


async def test_check_wcag_invalid_level(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "standards.check_wcag", {
        "content_id": seeded_ids["content_id"],
        "level": "B",
    })
    assert "error" in result


async def test_check_wcag_missing_ids_returns_error(server) -> None:
    result = await _call(server, "standards.check_wcag", {"level": "AA"})
    assert "error" in result


async def test_check_wcag_nonexistent_content(server) -> None:
    result = await _call(server, "standards.check_wcag", {
        "content_id": str(uuid.uuid4()),
        "level": "AA",
    })
    assert "error" in result


async def test_check_wcag_content_id_in_response(server, seeded_ids) -> None:
    if not seeded_ids["content_id"]:
        pytest.skip("No seeded content")
    result = await _call(server, "standards.check_wcag", {
        "content_id": seeded_ids["content_id"],
        "level": "AA",
    })
    assert result["content_id"] == seeded_ids["content_id"]


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


async def test_check_wcag_by_node_breaks_created_at_ties_by_id(server, tied_node) -> None:
    result = await _call(server, "standards.check_wcag", {"node_id": tied_node})
    assert result["content_id"] == str(_TIED_HIGH)
