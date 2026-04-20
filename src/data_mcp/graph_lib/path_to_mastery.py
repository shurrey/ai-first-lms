"""Compute the prerequisite chain from current mastery to a target node."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg


async def path_to_mastery(
    pool: asyncpg.Pool,
    person_id: UUID,
    target_node_id: UUID,
) -> dict[str, Any]:
    """Walk prerequisite_of edges backward from target and annotate with mastery.

    Returns a path of nodes from the earliest unmastered prerequisite to the
    target, each annotated with the person's current mastery level and confidence.
    """
    async with pool.acquire() as conn:
        # Get all prerequisite chains leading to target via recursive CTE
        prereq_rows = await conn.fetch(
            """
            WITH RECURSIVE prereqs AS (
                -- Base: the target itself
                SELECT $1::uuid AS node_id, 0 AS depth
                UNION ALL
                -- Recursive: nodes that are prerequisite_of the current node
                SELECT e.from_node AS node_id, p.depth + 1
                FROM prereqs p
                JOIN edges e ON e.to_node = p.node_id AND e.kind = 'prerequisite_of'
                WHERE p.depth < 20  -- safety cap
            )
            SELECT DISTINCT node_id, MIN(depth) AS depth
            FROM prereqs
            GROUP BY node_id
            ORDER BY depth DESC
            """,
            target_node_id,
        )

        node_ids = [row["node_id"] for row in prereq_rows]
        if not node_ids:
            return {"path": []}

        # Get node titles
        node_rows = await conn.fetch(
            "SELECT id, title, kind FROM nodes WHERE id = ANY($1)",
            node_ids,
        )
        node_map = {r["id"]: dict(r) for r in node_rows}

        # Get mastery evidence: latest attestation per node for this person
        attestation_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (node_id) node_id, level, issued_at
            FROM attestations
            WHERE person_id = $1 AND node_id = ANY($2)
            ORDER BY node_id, issued_at DESC
            """,
            person_id, node_ids,
        )
        attestation_map = {r["node_id"]: r["level"] for r in attestation_rows}

        # Get latest evidence confidence per node
        evidence_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (node_id) node_id, confidence, score
            FROM evidence
            WHERE person_id = $1 AND node_id = ANY($2)
            ORDER BY node_id, observed_at DESC
            """,
            person_id, node_ids,
        )
        evidence_map = {r["node_id"]: r for r in evidence_rows}

        path = []
        for row in prereq_rows:
            nid = row["node_id"]
            node_info = node_map.get(nid, {})
            ev = evidence_map.get(nid)
            path.append({
                "node_id": str(nid),
                "title": node_info.get("title", ""),
                "mastery_level": attestation_map.get(nid, "none"),
                "confidence": float(ev["confidence"]) if ev and ev["confidence"] is not None else 0.0,
                "depth": row["depth"],
            })

        return {"path": path}
