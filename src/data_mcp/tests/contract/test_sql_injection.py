"""Hostile-input contract tests for MCP tools that take caller-supplied SQL fragments."""
from __future__ import annotations

import json
import os

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.analytics.tools import (
    ATTESTATION_DIMENSIONS,
    EVIDENCE_DIMENSIONS,
)
from data_mcp.mcp_servers.analytics.tools import get_tools as analytics_tools
from data_mcp.mcp_servers.assessments.tools import get_tools as assessments_tools
from data_mcp.mcp_servers.content.tools import get_tools as content_tools
from data_mcp.mcp_servers.sis.tools import get_tools as sis_tools
from data_mcp.mcp_servers.standards.tools import get_tools as standards_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")

HOSTILE = ["x' OR '1'='1", "level; DROP TABLE nodes"]


class _NoDbPool:
    """Pool stand-in that fails the call if a handler reaches for a connection."""

    def acquire(self):
        raise AssertionError("handler touched the database before validating input")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest.fixture(scope="module")
def no_db():
    """Handlers bound to _NoDbPool, called directly so the MCP layer's schema check is bypassed."""
    stub = _NoDbPool()
    return {
        t.name: t.handler
        for t in [*content_tools(stub), *analytics_tools(stub), *assessments_tools(stub)]
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def servers(pool):
    return {
        "content": create_mcp_server("content", content_tools(pool)),
        "analytics": create_mcp_server("analytics", analytics_tools(pool)),
        "sis": create_mcp_server("sis", sis_tools(pool)),
        "standards": create_mcp_server("standards", standards_tools(pool)),
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def edge_node(pool) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT from_node FROM edges WHERE kind = 'part_of' LIMIT 1")
    if not row:
        pytest.skip("No seeded part_of edges")
    return str(row["from_node"])


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    text = result.root.content[0].text
    if result.root.isError:
        return {"mcp_error": text}
    return json.loads(text)


async def _table_counts(pool) -> tuple[int, int, int]:
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT to_regclass('public.nodes') IS NOT NULL")
        return (
            await conn.fetchval("SELECT COUNT(*) FROM nodes"),
            await conn.fetchval("SELECT COUNT(*) FROM edges"),
            await conn.fetchval("SELECT COUNT(*) FROM evidence"),
        )


def _assert_validation_error(result: dict) -> None:
    assert result.get("code") == "validation_error", result
    assert result.get("error")


# ---------------------------------------------------------------------------
# graph.neighbors kinds
# ---------------------------------------------------------------------------

_ANY_NODE = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("hostile", HOSTILE)
@pytest.mark.parametrize("as_list", [False, True])
async def test_neighbors_rejects_hostile_kinds_before_db(no_db, hostile, as_list) -> None:
    kinds = ["part_of", hostile] if as_list else hostile
    result = await no_db["graph.neighbors"]({"node_id": _ANY_NODE, "kinds": kinds})
    _assert_validation_error(result)


@pytest.mark.parametrize("hostile", HOSTILE)
async def test_neighbors_schema_rejects_hostile_kind_list(servers, hostile) -> None:
    result = await _call(servers["content"], "graph.neighbors", {
        "node_id": _ANY_NODE, "kinds": ["part_of", hostile],
    })
    assert "mcp_error" in result


@pytest.mark.parametrize("hostile", HOSTILE)
async def test_neighbors_hostile_kinds_leave_tables_intact(
    servers, pool, edge_node, hostile,
) -> None:
    before = await _table_counts(pool)
    result = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "kinds": hostile,
    })
    _assert_validation_error(result)
    assert await _table_counts(pool) == before


async def test_neighbors_rejects_non_string_kinds(no_db) -> None:
    result = await no_db["graph.neighbors"]({"node_id": _ANY_NODE, "kinds": [1, 2]})
    _assert_validation_error(result)


async def test_neighbors_rejects_unknown_direction(no_db) -> None:
    result = await no_db["graph.neighbors"]({"node_id": _ANY_NODE, "direction": "sideways"})
    _assert_validation_error(result)


async def test_neighbors_kinds_string_filters(servers, edge_node) -> None:
    result = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "kinds": "part_of", "direction": "outgoing",
    })
    assert "error" not in result
    assert result["nodes"]
    assert {n["edge_kind"] for n in result["nodes"]} == {"part_of"}


async def test_neighbors_kinds_list_filters(servers, edge_node) -> None:
    result = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "kinds": ["part_of", "prerequisite_of"],
    })
    assert "error" not in result
    assert result["nodes"]
    assert {n["edge_kind"] for n in result["nodes"]} <= {"part_of", "prerequisite_of"}


async def test_neighbors_kinds_comma_separated(servers, edge_node) -> None:
    as_list = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "kinds": ["part_of", "prerequisite_of"],
    })
    as_csv = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "kinds": "part_of, prerequisite_of",
    })
    assert sorted(n["id"] for n in as_csv["nodes"]) == sorted(n["id"] for n in as_list["nodes"])


async def test_neighbors_contract_direction_aliases(servers, edge_node) -> None:
    out = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "direction": "out",
    })
    outgoing = await _call(servers["content"], "graph.neighbors", {
        "node_id": edge_node, "direction": "outgoing",
    })
    def key(n: dict) -> tuple:
        return (n["id"], n["edge_kind"])

    assert sorted(out["nodes"], key=key) == sorted(outgoing["nodes"], key=key)


# ---------------------------------------------------------------------------
# analytics.query breakdown
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hostile", HOSTILE)
@pytest.mark.parametrize(
    "metric", ["evidence_count", "avg_score", "engagement_count", "mastery_rate"],
)
async def test_query_rejects_hostile_breakdown_before_db(no_db, hostile, metric) -> None:
    result = await no_db["analytics.query"]({
        "scope": {}, "metric": metric, "window": {}, "breakdown": hostile,
    })
    _assert_validation_error(result)
    assert result["rows"] == []


@pytest.mark.parametrize("hostile", HOSTILE)
async def test_query_hostile_breakdown_leaves_tables_intact(servers, pool, hostile) -> None:
    before = await _table_counts(pool)
    result = await _call(servers["analytics"], "analytics.query", {
        "scope": {}, "metric": "evidence_count", "window": {}, "breakdown": hostile,
    })
    _assert_validation_error(result)
    assert await _table_counts(pool) == before


async def test_query_rejects_dimension_from_other_table(no_db) -> None:
    result = await no_db["analytics.query"]({
        "scope": {}, "metric": "mastery_rate", "window": {}, "breakdown": "kind",
    })
    _assert_validation_error(result)


@pytest.mark.parametrize("dimension", sorted(EVIDENCE_DIMENSIONS))
async def test_query_evidence_breakdown_allowed(servers, dimension) -> None:
    result = await _call(servers["analytics"], "analytics.query", {
        "scope": {}, "metric": "evidence_count", "window": {}, "breakdown": dimension,
    })
    assert "error" not in result
    assert result["rows"]
    assert all("dimension" in r for r in result["rows"])


@pytest.mark.parametrize("dimension", sorted(ATTESTATION_DIMENSIONS))
async def test_query_attestation_breakdown_allowed(servers, dimension) -> None:
    result = await _call(servers["analytics"], "analytics.query", {
        "scope": {}, "metric": "mastery_rate", "window": {}, "breakdown": dimension,
    })
    assert "error" not in result
    assert result["rows"]
    assert all("dimension" in r for r in result["rows"])


async def test_describe_schema_dimensions_are_all_accepted(servers) -> None:
    schema = await _call(servers["analytics"], "analytics.describe_schema", {})
    assert set(schema["dimensions"]) == EVIDENCE_DIMENSIONS | ATTESTATION_DIMENSIONS


@pytest.mark.parametrize("bad_kind", [*HOSTILE, "not_a_kind", ["attempt"], 7])
async def test_query_rejects_invalid_filter_kind_before_db(no_db, bad_kind) -> None:
    result = await no_db["analytics.query"]({
        "scope": {}, "metric": "evidence_count", "window": {}, "filters": {"kind": bad_kind},
    })
    _assert_validation_error(result)
    assert result["rows"] == []


_BAD_SHAPES = [
    ("metric", ["evidence_count"]),
    ("scope", "cs101"),
    ("window", ["2026-01-01"]),
    ("scope", {"person_id": "x' OR '1'='1"}),
    ("filters", {"node_id": "level; DROP TABLE nodes"}),
    ("window", {"start": "x' OR '1'='1"}),
]


@pytest.mark.parametrize(("field", "value"), _BAD_SHAPES)
@pytest.mark.parametrize("tool", ["analytics.query", "analytics.trend", "analytics.cohort_compare"])
async def test_analytics_rejects_malformed_args_before_db(no_db, tool, field, value) -> None:
    args = {"scope": {}, "metric": "evidence_count", "window": {}, "interval": "day",
            "cohorts": [{"label": "a", "scope": {}}], field: value}
    if field == "filters" and tool != "analytics.query":
        pytest.skip("only analytics.query takes filters")
    _assert_validation_error(await no_db[tool](args))


async def test_query_valid_filter_kind(servers) -> None:
    result = await _call(servers["analytics"], "analytics.query", {
        "scope": {}, "metric": "evidence_count", "window": {}, "filters": {"kind": "attempt"},
    })
    assert "error" not in result
    assert result["rows"]


async def test_query_breakdown_totals_match_ungrouped(servers) -> None:
    total = await _call(servers["analytics"], "analytics.query", {
        "scope": {}, "metric": "evidence_count", "window": {},
    })
    by_kind = await _call(servers["analytics"], "analytics.query", {
        "scope": {}, "metric": "evidence_count", "window": {}, "breakdown": "kind",
    })
    assert sum(r["value"] for r in by_kind["rows"]) == total["rows"][0]["value"]


# ---------------------------------------------------------------------------
# Bound parameters: hostile strings are treated as data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hostile", HOSTILE)
async def test_bound_filters_treat_hostile_input_as_data(servers, pool, hostile) -> None:
    before = await _table_counts(pool)
    async with pool.acquire() as conn:
        framework = await conn.fetchval("SELECT name FROM standards_frameworks LIMIT 1")

    calls = [
        (servers["content"], "content.library_search", {"query": "", "kind": hostile}, "items"),
        (servers["content"], "content.search", {"query": "", "course_id": hostile}, "results"),
        (servers["sis"], "sis.catalog_search",
         {"query": hostile, "subject": hostile, "level": hostile, "term": hostile}, "courses"),
    ]
    if framework:
        calls.append(
            (servers["standards"], "standards.lookup",
             {"framework": framework, "code": hostile, "query": hostile}, "standards"),
        )
    for server, name, args, key in calls:
        result = await _call(server, name, args)
        assert "error" not in result, (name, result)
        assert result[key] == [], (name, result)

    assert await _table_counts(pool) == before


# ---------------------------------------------------------------------------
# assessments.list_recent_evidence since_days
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_days", [*HOSTILE, "1 day", -1, 1.5, True, None])
async def test_recent_evidence_rejects_invalid_since_days_before_db(no_db, bad_days) -> None:
    result = await no_db["assessments.list_recent_evidence"]({
        "person_id": _ANY_NODE, "since_days": bad_days,
    })
    _assert_validation_error(result)
    assert result["evidence"] == []


@pytest.mark.parametrize("days", [30, "30"])
async def test_recent_evidence_accepts_integer_since_days(pool, days) -> None:
    handlers = {t.name: t.handler for t in assessments_tools(pool)}
    async with pool.acquire() as conn:
        person_id = await conn.fetchval("SELECT person_id FROM evidence LIMIT 1")
    if person_id is None:
        pytest.skip("no evidence rows seeded")
    result = await handlers["assessments.list_recent_evidence"]({
        "person_id": str(person_id), "since_days": days,
    })
    assert "error" not in result
    assert isinstance(result["evidence"], list)
