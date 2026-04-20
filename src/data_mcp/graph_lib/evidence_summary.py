"""Aggregate mastery evidence for a person across nodes."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg


async def evidence_summary(
    pool: asyncpg.Pool,
    person_id: UUID,
    node_ids: list[UUID],
) -> dict[str, Any]:
    """Return aggregated evidence per node for a given person.

    For each node: mastery level (from latest attestation), evidence count,
    average score, and last observation timestamp.
    """
    async with pool.acquire() as conn:
        # Aggregate evidence
        ev_rows = await conn.fetch(
            """
            SELECT node_id,
                   COUNT(*) AS evidence_count,
                   AVG(score) AS avg_score,
                   MAX(observed_at) AS last_observed
            FROM evidence
            WHERE person_id = $1 AND node_id = ANY($2)
            GROUP BY node_id
            """,
            person_id, node_ids,
        )
        ev_map = {r["node_id"]: dict(r) for r in ev_rows}

        # Latest attestation per node
        att_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (node_id) node_id, level
            FROM attestations
            WHERE person_id = $1 AND node_id = ANY($2)
            ORDER BY node_id, issued_at DESC
            """,
            person_id, node_ids,
        )
        att_map = {r["node_id"]: r["level"] for r in att_rows}

        summaries = []
        for nid in node_ids:
            ev = ev_map.get(nid, {})
            summaries.append({
                "node_id": str(nid),
                "mastery": att_map.get(nid, "none"),
                "evidence_count": ev.get("evidence_count", 0),
                "avg_score": float(ev["avg_score"]) if ev.get("avg_score") is not None else None,
                "last_observed": ev["last_observed"].isoformat() if ev.get("last_observed") else None,
            })

        return {"summaries": summaries}
