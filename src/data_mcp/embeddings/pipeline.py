"""Embedding pipeline for node descriptions using pgvector.

For the prototype, uses a deterministic hash-based embedding approach.
This avoids requiring an API key during seeding while maintaining
cosine-similarity-based search functionality. Swap in a real embedding
model (Voyage, OpenAI, or sentence-transformers) for production.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any
from uuid import UUID

import asyncpg

EMBEDDING_DIM = 1536


def embed_text(text: str) -> list[float]:
    """Generate a deterministic pseudo-embedding from text.

    Uses character-level hashing to create a 1536-dimensional vector.
    Texts sharing words will have higher cosine similarity. Not as good
    as a real embedding model but sufficient for prototype search demos.
    """
    vec = [0.0] * EMBEDDING_DIM

    # Word-level features: each word contributes to specific dimensions
    words = text.lower().split()
    for word in words:
        h = hashlib.sha256(word.encode()).digest()
        for i in range(0, min(len(h), 32), 4):
            dim = int.from_bytes(h[i : i + 2], "big") % EMBEDDING_DIM
            val = (int.from_bytes(h[i + 2 : i + 4], "big") / 65535.0) * 2 - 1
            vec[dim] += val

    # Character n-gram features for fuzzier matching
    for i in range(len(text) - 2):
        trigram = text[i : i + 3].lower()
        h = hashlib.md5(trigram.encode()).digest()
        dim = int.from_bytes(h[:2], "big") % EMBEDDING_DIM
        val = (int.from_bytes(h[2:4], "big") / 65535.0) * 2 - 1
        vec[dim] += val * 0.3

    # Normalize to unit vector
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]

    return vec


async def embed_all_nodes(pool: asyncpg.Pool, batch_size: int = 100) -> int:
    """Embed all nodes that don't have embeddings yet.

    Returns the number of nodes embedded.
    """
    count = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, COALESCE(description, '') AS description
               FROM nodes WHERE embedding IS NULL"""
        )
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            for row in batch:
                text = f"{row['title']} {row['description']}"
                vec = embed_text(text)
                await conn.execute(
                    "UPDATE nodes SET embedding = $1 WHERE id = $2",
                    str(vec), row["id"],
                )
                count += 1

    return count


async def search_similar(
    pool: asyncpg.Pool,
    query: str,
    top_k: int = 10,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """Find nodes most similar to the query using cosine distance."""
    query_vec = embed_text(query)

    async with pool.acquire() as conn:
        if kind:
            rows = await conn.fetch(
                """SELECT id, title, description, kind,
                          1 - (embedding <=> $1::vector) AS similarity
                   FROM nodes
                   WHERE embedding IS NOT NULL AND kind = $3
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                str(query_vec), top_k, kind,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, title, description, kind,
                          1 - (embedding <=> $1::vector) AS similarity
                   FROM nodes
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                str(query_vec), top_k,
            )

        return [
            {
                "node_id": str(r["id"]),
                "title": r["title"],
                "description": r["description"] or "",
                "kind": r["kind"],
                "similarity": round(float(r["similarity"]), 4),
            }
            for r in rows
        ]
