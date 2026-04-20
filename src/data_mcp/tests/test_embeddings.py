"""Tests for the embedding pipeline."""
from __future__ import annotations

import math
import os

import asyncpg
import pytest
import pytest_asyncio

from data_mcp.embeddings.pipeline import embed_text, embed_all_nodes, search_similar

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")
pytestmark = pytest.mark.asyncio(loop_scope="module")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def test_embed_text_dimension() -> None:
    vec = embed_text("hello world")
    assert len(vec) == 1536


def test_embed_text_normalized() -> None:
    vec = embed_text("recursion base case")
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 0.01


def test_embed_text_deterministic() -> None:
    v1 = embed_text("control flow")
    v2 = embed_text("control flow")
    assert v1 == v2


def test_embed_text_similar_texts_high_similarity() -> None:
    v1 = embed_text("recursion and base cases")
    v2 = embed_text("recursive base case")
    v3 = embed_text("file I/O and reading CSV")
    sim_related = _cosine_similarity(v1, v2)
    sim_unrelated = _cosine_similarity(v1, v3)
    assert sim_related > sim_unrelated


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


async def test_embed_all_nodes(pool) -> None:
    # Clear embeddings first
    async with pool.acquire() as conn:
        await conn.execute("UPDATE nodes SET embedding = NULL")
    count = await embed_all_nodes(pool)
    assert count > 0

    # Verify embeddings are stored
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS c FROM nodes WHERE embedding IS NOT NULL"
        )
        assert row["c"] == count


async def test_search_similar_finds_relevant_nodes(pool) -> None:
    results = await search_similar(pool, "recursion", top_k=5)
    assert len(results) > 0
    # Top result should have positive similarity
    assert results[0]["similarity"] > 0
    # Results should be sorted by similarity descending
    sims = [r["similarity"] for r in results]
    assert sims == sorted(sims, reverse=True)


async def test_search_similar_with_kind_filter(pool) -> None:
    results = await search_similar(pool, "variables", top_k=5, kind="concept")
    assert len(results) > 0
    assert all(r["kind"] == "concept" for r in results)
