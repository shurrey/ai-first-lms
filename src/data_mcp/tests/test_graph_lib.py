"""Tests for the graph library functions."""
from __future__ import annotations

# All async tests and fixtures in this module share one event loop.
import pytest
pytestmark = pytest.mark.asyncio(loop_scope="module")

import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest_asyncio

from data_mcp.graph_lib.aggregate import aggregate
from data_mcp.graph_lib.evidence_summary import evidence_summary
from data_mcp.graph_lib.neighbors import neighbors
from data_mcp.graph_lib.path_to_mastery import path_to_mastery
from data_mcp.graph_lib.subgraph import subgraph

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def graph_data(pool: asyncpg.Pool) -> dict:
    """Seed a small graph: A -> B -> C (prerequisite chain), plus person + evidence."""
    ids: dict = {}

    async with pool.acquire() as conn:
        # Clean up
        await conn.execute("DELETE FROM attestations")
        await conn.execute("DELETE FROM evidence")
        await conn.execute("DELETE FROM grades")
        await conn.execute("DELETE FROM submissions")
        await conn.execute("DELETE FROM enrollments")
        await conn.execute("DELETE FROM edges")
        await conn.execute("DELETE FROM content_items")
        await conn.execute("DELETE FROM nodes")
        await conn.execute("DELETE FROM persons")

        # Nodes: A -> B -> C (prerequisite chain)
        a = uuid.uuid4()
        b = uuid.uuid4()
        c = uuid.uuid4()
        ids["a"] = a
        ids["b"] = b
        ids["c"] = c

        for nid, title in [(a, "Node A"), (b, "Node B"), (c, "Node C")]:
            await conn.execute(
                "INSERT INTO nodes (id, kind, title) VALUES ($1, 'concept', $2)",
                nid, title,
            )

        # Edges: A prerequisite_of B, B prerequisite_of C
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
            a, b,
        )
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
            b, c,
        )

        # An extra node D with variant_of edge to A
        d = uuid.uuid4()
        ids["d"] = d
        await conn.execute(
            "INSERT INTO nodes (id, kind, title) VALUES ($1, 'concept', 'Node D')", d,
        )
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'variant_of')",
            d, a,
        )

        # Person
        person = uuid.uuid4()
        ids["person"] = person
        await conn.execute(
            "INSERT INTO persons (id, roles, display_name) VALUES ($1, $2, 'Test User')",
            person, ["student"],
        )

        # Evidence for person on node A and B
        now = datetime.now(timezone.utc)
        await conn.execute(
            """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
               VALUES ($1, $2, 'attempt', 0.8, 0.9, 'test', $3)""",
            person, a, now,
        )
        await conn.execute(
            """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
               VALUES ($1, $2, 'completion', 0.95, 0.85, 'test', $3)""",
            person, a, now,
        )
        await conn.execute(
            """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
               VALUES ($1, $2, 'attempt', 0.6, 0.7, 'test', $3)""",
            person, b, now,
        )

        # Attestation for person on node A
        await conn.execute(
            """INSERT INTO attestations (person_id, node_id, level, issuer_id)
               VALUES ($1, $2, 'proficient', $1)""",
            person, a,
        )

        # Engagement event for aggregate testing
        await conn.execute(
            """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
               VALUES ($1, $2, 'engagement_event', NULL, NULL, 'test', $3)""",
            person, a, now,
        )

    return ids


# ---- neighbors ----

async def test_neighbors_out(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await neighbors(pool, graph_data["a"], direction="out", depth=1)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["b"]) in node_ids
    assert len(result["edges"]) >= 1


async def test_neighbors_in(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await neighbors(pool, graph_data["b"], direction="in", depth=1)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["a"]) in node_ids


async def test_neighbors_both(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await neighbors(pool, graph_data["b"], direction="both", depth=1)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["a"]) in node_ids
    assert str(graph_data["c"]) in node_ids


async def test_neighbors_edge_kind_filter(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await neighbors(pool, graph_data["a"], edge_kind="variant_of", direction="both", depth=1)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["d"]) in node_ids
    # prerequisite edges should be excluded
    assert str(graph_data["b"]) not in node_ids


async def test_neighbors_depth_2(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await neighbors(pool, graph_data["a"], direction="out", depth=2)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["b"]) in node_ids
    assert str(graph_data["c"]) in node_ids


# ---- subgraph ----

async def test_subgraph_from_root(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await subgraph(pool, [graph_data["a"]], max_depth=2)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["a"]) in node_ids
    assert str(graph_data["b"]) in node_ids
    assert str(graph_data["c"]) in node_ids
    assert len(result["edges"]) >= 2


async def test_subgraph_depth_1(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await subgraph(pool, [graph_data["a"]], max_depth=1)
    node_ids = {n["id"] for n in result["nodes"]}
    assert str(graph_data["b"]) in node_ids
    assert str(graph_data["d"]) in node_ids


# ---- path_to_mastery ----

async def test_path_to_mastery_basic(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await path_to_mastery(pool, graph_data["person"], graph_data["c"])
    path = result["path"]
    assert len(path) >= 2
    # A should have mastery_level 'proficient'
    a_entry = next((p for p in path if p["node_id"] == str(graph_data["a"])), None)
    assert a_entry is not None
    assert a_entry["mastery_level"] == "proficient"
    # C should have no mastery
    c_entry = next((p for p in path if p["node_id"] == str(graph_data["c"])), None)
    assert c_entry is not None
    assert c_entry["mastery_level"] == "none"


# ---- evidence_summary ----

async def test_evidence_summary_basic(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await evidence_summary(pool, graph_data["person"], [graph_data["a"], graph_data["b"], graph_data["c"]])
    summaries = result["summaries"]
    assert len(summaries) == 3

    a_sum = next(s for s in summaries if s["node_id"] == str(graph_data["a"]))
    assert a_sum["mastery"] == "proficient"
    assert a_sum["evidence_count"] >= 2
    assert a_sum["avg_score"] is not None

    b_sum = next(s for s in summaries if s["node_id"] == str(graph_data["b"]))
    assert b_sum["mastery"] == "none"
    assert b_sum["evidence_count"] >= 1

    c_sum = next(s for s in summaries if s["node_id"] == str(graph_data["c"]))
    assert c_sum["evidence_count"] == 0
    assert c_sum["avg_score"] is None


# ---- aggregate ----

async def test_aggregate_evidence_count(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await aggregate(
        pool,
        scope={"person_id": str(graph_data["person"])},
        metric="evidence_count",
        window={"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
    )
    assert result["value"] >= 3


async def test_aggregate_avg_score(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await aggregate(
        pool,
        scope={"person_id": str(graph_data["person"])},
        metric="avg_score",
        window={"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
    )
    assert 0 < result["value"] < 1


async def test_aggregate_unknown_metric(pool: asyncpg.Pool, graph_data: dict) -> None:
    result = await aggregate(pool, scope={}, metric="nonexistent", window={})
    assert result["value"] == 0
    assert "Unknown metric" in result["caveats"][0]
