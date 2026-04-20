"""Contract tests for the analytics MCP server tools."""
from __future__ import annotations

import json
import os

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.analytics.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("analytics", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    """Get IDs from the seeded CS 101 data."""
    async with pool.acquire() as conn:
        course = await conn.fetchrow("SELECT course_id FROM courses LIMIT 1")
        person = await conn.fetchrow("SELECT id FROM persons WHERE roles @> '{student}' LIMIT 1")
    return {
        "course_id": str(course["course_id"]) if course else None,
        "person_id": str(person["id"]) if person else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


# ---------------------------------------------------------------------------
# analytics.describe_schema
# ---------------------------------------------------------------------------

async def test_describe_schema(server) -> None:
    result = await _call(server, "analytics.describe_schema", {})
    assert "tables" in result
    assert "events" in result
    assert "metrics" in result
    assert "dimensions" in result
    assert isinstance(result["tables"], list)
    assert isinstance(result["metrics"], list)
    assert "evidence_count" in result["metrics"]


# ---------------------------------------------------------------------------
# analytics.query
# ---------------------------------------------------------------------------

async def test_query_evidence_count_no_scope(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "evidence_count",
        "window": {},
    })
    assert "rows" in result
    assert "metadata" in result
    assert isinstance(result["rows"], list)
    # At least one aggregate row expected when DB has seeded data
    if result["rows"]:
        assert "value" in result["rows"][0]
        assert "sample_size" in result["rows"][0]


async def test_query_evidence_count_by_course(server, seeded_ids) -> None:
    if not seeded_ids["course_id"]:
        pytest.skip("No seeded course")
    result = await _call(server, "analytics.query", {
        "scope": {"course_id": seeded_ids["course_id"]},
        "metric": "evidence_count",
        "window": {},
    })
    assert "rows" in result
    assert isinstance(result["rows"], list)


async def test_query_avg_score(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "avg_score",
        "window": {},
    })
    assert "rows" in result
    assert isinstance(result["rows"], list)


async def test_query_mastery_rate(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "mastery_rate",
        "window": {},
    })
    assert "rows" in result
    assert isinstance(result["rows"], list)


async def test_query_engagement_count(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "engagement_count",
        "window": {},
    })
    assert "rows" in result
    assert isinstance(result["rows"], list)


async def test_query_unknown_metric(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "nonexistent_metric",
        "window": {},
    })
    assert "rows" in result
    assert result["metadata"].get("error") or result["rows"] == []


async def test_query_with_window(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "evidence_count",
        "window": {"start": "2020-01-01T00:00:00Z", "end": "2099-12-31T23:59:59Z"},
    })
    assert "rows" in result


async def test_query_with_kind_filter(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "evidence_count",
        "window": {},
        "filters": {"kind": "attempt"},
    })
    assert "rows" in result
    assert isinstance(result["rows"], list)


async def test_query_metadata_shape(server) -> None:
    result = await _call(server, "analytics.query", {
        "scope": {},
        "metric": "evidence_count",
        "window": {},
    })
    meta = result.get("metadata", {})
    assert "metric" in meta
    assert meta["metric"] == "evidence_count"


# ---------------------------------------------------------------------------
# analytics.trend
# ---------------------------------------------------------------------------

async def test_trend_daily(server) -> None:
    result = await _call(server, "analytics.trend", {
        "scope": {},
        "metric": "evidence_count",
        "window": {},
        "interval": "day",
    })
    assert "series" in result
    assert isinstance(result["series"], list)


async def test_trend_monthly(server, seeded_ids) -> None:
    if not seeded_ids["course_id"]:
        pytest.skip("No seeded course")
    result = await _call(server, "analytics.trend", {
        "scope": {"course_id": seeded_ids["course_id"]},
        "metric": "evidence_count",
        "window": {},
        "interval": "month",
    })
    assert "series" in result
    for point in result["series"]:
        assert "x" in point
        assert "y" in point


async def test_trend_avg_score(server) -> None:
    result = await _call(server, "analytics.trend", {
        "scope": {},
        "metric": "avg_score",
        "window": {},
        "interval": "week",
    })
    assert "series" in result
    assert isinstance(result["series"], list)


async def test_trend_engagement(server) -> None:
    result = await _call(server, "analytics.trend", {
        "scope": {},
        "metric": "engagement_count",
        "window": {},
        "interval": "day",
    })
    assert "series" in result


# ---------------------------------------------------------------------------
# analytics.cohort_compare
# ---------------------------------------------------------------------------

async def test_cohort_compare_basic(server, seeded_ids) -> None:
    if not seeded_ids["course_id"]:
        pytest.skip("No seeded course")
    cohorts = [
        {"label": "All students", "scope": {}},
        {"label": "Course students", "scope": {"course_id": seeded_ids["course_id"]}},
    ]
    result = await _call(server, "analytics.cohort_compare", {
        "scope": {},
        "cohorts": cohorts,
        "metric": "evidence_count",
        "window": {},
    })
    assert "cohort_results" in result
    assert len(result["cohort_results"]) == 2
    for cr in result["cohort_results"]:
        assert "cohort" in cr
        assert "value" in cr
        assert "sample_size" in cr


async def test_cohort_compare_empty_cohorts(server) -> None:
    result = await _call(server, "analytics.cohort_compare", {
        "scope": {},
        "cohorts": [],
        "metric": "evidence_count",
        "window": {},
    })
    assert "cohort_results" in result
    assert result["cohort_results"] == []


async def test_cohort_compare_avg_score(server) -> None:
    cohorts = [
        {"label": "group_a", "scope": {}},
    ]
    result = await _call(server, "analytics.cohort_compare", {
        "scope": {},
        "cohorts": cohorts,
        "metric": "avg_score",
        "window": {},
    })
    assert "cohort_results" in result
    assert len(result["cohort_results"]) == 1


# ---------------------------------------------------------------------------
# analytics.render_chart
# ---------------------------------------------------------------------------

async def test_render_chart_line(server) -> None:
    series = [{"x": "2024-01-01", "y": 10}, {"x": "2024-01-02", "y": 20}]
    result = await _call(server, "analytics.render_chart", {
        "series": series,
        "type": "line",
        "title": "Evidence Over Time",
    })
    assert "chart_spec" in result
    spec = result["chart_spec"]
    assert spec["type"] == "line"
    assert spec["title"] == "Evidence Over Time"
    assert spec["data"] == series
    assert "xKey" in spec
    assert "yKey" in spec


async def test_render_chart_bar(server) -> None:
    series = [{"x": "Module 1", "y": 5}, {"x": "Module 2", "y": 8}]
    result = await _call(server, "analytics.render_chart", {
        "series": series,
        "type": "bar",
        "title": "Evidence by Module",
    })
    assert "chart_spec" in result
    assert result["chart_spec"]["type"] == "bar"


async def test_render_chart_histogram(server) -> None:
    series = [{"y": 0.5}, {"y": 0.8}, {"y": 0.9}]
    result = await _call(server, "analytics.render_chart", {
        "series": series,
        "type": "histogram",
        "title": "Score Distribution",
    })
    assert "chart_spec" in result
    spec = result["chart_spec"]
    assert spec["type"] == "histogram"
    assert "bins" in spec


async def test_render_chart_scatter(server) -> None:
    series = [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]
    result = await _call(server, "analytics.render_chart", {
        "series": series,
        "type": "scatter",
        "title": "Correlation",
    })
    assert "chart_spec" in result
    assert result["chart_spec"]["type"] == "scatter"


async def test_render_chart_empty_series(server) -> None:
    result = await _call(server, "analytics.render_chart", {
        "series": [],
        "type": "line",
        "title": "Empty Chart",
    })
    assert "chart_spec" in result
    assert result["chart_spec"]["data"] == []
