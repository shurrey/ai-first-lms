"""Extract a bounded subgraph from a set of root nodes."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg


async def subgraph(
    pool: asyncpg.Pool,
    root_ids: list[UUID],
    max_depth: int,
) -> dict[str, Any]:
    """Return all nodes and edges reachable from root_ids within max_depth.

    Traverses both directions to capture the full local neighborhood.
    """
    async with pool.acquire() as conn:
        visited: set[UUID] = set(root_ids)
        all_edges: list[dict] = []
        frontier: list[UUID] = list(root_ids)

        for _ in range(max_depth):
            if not frontier:
                break
            rows = await conn.fetch(
                """SELECT e.id, e.from_node, e.to_node, e.kind, e.weight, e.metadata
                   FROM edges e
                   WHERE e.from_node = ANY($1) OR e.to_node = ANY($1)""",
                frontier,
            )
            next_frontier: set[UUID] = set()
            for row in rows:
                edge = dict(row)
                edge["id"] = str(edge["id"])
                edge["from_node"] = str(edge["from_node"])
                edge["to_node"] = str(edge["to_node"])
                all_edges.append(edge)

                for col in ("from_node", "to_node"):
                    nid = row[col]
                    if nid not in visited:
                        visited.add(nid)
                        next_frontier.add(nid)

            frontier = list(next_frontier)

        # Fetch node details
        node_rows = await conn.fetch(
            """SELECT id, kind, title, description, tags, metadata
               FROM nodes WHERE id = ANY($1)""",
            list(visited),
        )
        nodes = [
            {**dict(r), "id": str(r["id"])}
            for r in node_rows
        ]

        # Deduplicate edges
        seen: set[str] = set()
        unique_edges = []
        for e in all_edges:
            if e["id"] not in seen:
                seen.add(e["id"])
                unique_edges.append(e)

        return {"nodes": nodes, "edges": unique_edges}
