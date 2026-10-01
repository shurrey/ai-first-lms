"""Graph neighbors: BFS traversal up to a given depth."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg


async def neighbors(
    pool: asyncpg.Pool,
    node_id: UUID,
    edge_kind: str | None = None,
    direction: str = "both",
    depth: int = 1,
) -> dict[str, Any]:
    """Return nodes and edges reachable from node_id within depth hops.

    Args:
        pool: asyncpg connection pool
        node_id: starting node
        edge_kind: filter to a specific edge kind (or None for all)
        direction: 'in', 'out', or 'both'
        depth: maximum traversal depth (BFS)

    Returns:
        {"nodes": [...], "edges": [...]}
    """
    edge_cols = "SELECT e.id, e.from_node, e.to_node, e.kind, e.weight, e.metadata FROM edges e"
    kind_clause = "($2::text IS NULL OR e.kind::text = $2)"
    if direction == "out":
        edge_sql = edge_cols + " WHERE e.from_node = ANY($1) AND " + kind_clause
        next_col = "to_node"
    elif direction == "in":
        edge_sql = edge_cols + " WHERE e.to_node = ANY($1) AND " + kind_clause
        next_col = "from_node"
    else:  # both
        edge_sql = (
            edge_cols + " WHERE (e.from_node = ANY($1) OR e.to_node = ANY($1)) AND " + kind_clause
        )
        next_col = None  # handled below

    async with pool.acquire() as conn:
        visited_nodes: set[UUID] = {node_id}
        all_edges: list[dict] = []
        frontier: list[UUID] = [node_id]

        for _ in range(depth):
            rows = await conn.fetch(edge_sql, frontier, edge_kind)

            next_frontier: set[UUID] = set()
            for row in rows:
                edge = dict(row)
                edge["id"] = str(edge["id"])
                edge["from_node"] = str(edge["from_node"])
                edge["to_node"] = str(edge["to_node"])
                all_edges.append(edge)

                if next_col:
                    nid = row[next_col]
                    if nid not in visited_nodes:
                        next_frontier.add(nid)
                        visited_nodes.add(nid)
                else:
                    for col in ("from_node", "to_node"):
                        nid = row[col]
                        if nid not in visited_nodes:
                            next_frontier.add(nid)
                            visited_nodes.add(nid)

            frontier = list(next_frontier)
            if not frontier:
                break

        # Fetch node details for all visited nodes (except root which caller already has)
        node_rows = await conn.fetch(
            """SELECT id, kind, title, description, tags, metadata
               FROM nodes WHERE id = ANY($1)""",
            list(visited_nodes),
        )
        nodes = []
        for r in node_rows:
            n = dict(r)
            n["id"] = str(n["id"])
            nodes.append(n)

        # Deduplicate edges
        seen_edge_ids: set[str] = set()
        unique_edges = []
        for e in all_edges:
            if e["id"] not in seen_edge_ids:
                seen_edge_ids.add(e["id"])
                unique_edges.append(e)

        return {"nodes": nodes, "edges": unique_edges}
