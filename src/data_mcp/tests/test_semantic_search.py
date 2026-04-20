"""Tests for semantic search fallback in the content server."""
from __future__ import annotations

import json
import os

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.embeddings.pipeline import embed_all_nodes
from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.content.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    # Ensure embeddings exist
    await embed_all_nodes(p)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("content", get_tools(pool))


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


async def test_semantic_search_finds_related_content(server) -> None:
    """A query that matches semantically but not by exact keyword should return results."""
    # "How do loops work?" should find content related to "Control Flow" module
    result = await _call(server, "content.search", {
        "query": "How do loops work",
        "top_k": 5,
    })
    assert "results" in result
    # We should get results even if the exact phrase isn't in any content title
    assert len(result["results"]) > 0


async def test_keyword_search_still_works(server) -> None:
    """Exact keyword matches should still appear first."""
    result = await _call(server, "content.search", {
        "query": "Variables",
        "top_k": 10,
    })
    assert "results" in result
    assert len(result["results"]) > 0
    # Keyword matches get score 1.0
    assert any(r["score"] == 1.0 for r in result["results"])


async def test_results_are_deduplicated(server) -> None:
    """Results should not contain duplicates even when both keyword and semantic match."""
    result = await _call(server, "content.search", {
        "query": "Variables",
        "top_k": 20,
    })
    ids = [r["id"] for r in result["results"]]
    assert len(ids) == len(set(ids)), "Duplicate results found"


async def test_results_sorted_by_score(server) -> None:
    """Results should be sorted by score descending."""
    result = await _call(server, "content.search", {
        "query": "recursion",
        "top_k": 10,
    })
    scores = [r["score"] for r in result["results"]]
    assert scores == sorted(scores, reverse=True)
