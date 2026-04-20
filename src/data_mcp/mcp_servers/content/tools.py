"""Content MCP server tool handlers."""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all content server tool definitions."""

    async def retrieve(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args.get("node_id")
        content_id = args.get("content_id")
        async with pool.acquire() as conn:
            if content_id:
                row = await conn.fetchrow(
                    """SELECT ci.id, ci.title, ci.body_md, ci.kind, ci.metadata,
                              n.title AS node_title
                       FROM content_items ci
                       LEFT JOIN nodes n ON n.id = ci.node_id
                       WHERE ci.id = $1""",
                    uuid.UUID(content_id),
                )
            elif node_id:
                row = await conn.fetchrow(
                    """SELECT ci.id, ci.title, ci.body_md, ci.kind, ci.metadata,
                              n.title AS node_title
                       FROM content_items ci
                       LEFT JOIN nodes n ON n.id = ci.node_id
                       WHERE ci.node_id = $1
                       ORDER BY ci.created_at DESC LIMIT 1""",
                    uuid.UUID(node_id),
                )
            else:
                return {"error": "Either node_id or content_id is required"}

            if not row:
                return {"error": "Content not found"}
            return {
                "id": str(row["id"]),
                "title": row["title"],
                "body_md": row["body_md"] or "",
                "citations": [],
            }

    async def search(args: dict[str, Any]) -> dict[str, Any]:
        from data_mcp.embeddings.pipeline import embed_text

        query = args.get("query", "")
        course_id = args.get("course_id")
        top_k = args.get("top_k", 10)

        async with pool.acquire() as conn:
            # Step 1: keyword search via ILIKE
            conditions = ["(ci.title ILIKE $1 OR ci.body_md ILIKE $1)"]
            params: list[Any] = [f"%{query}%"]
            idx = 2

            if course_id:
                conditions.append(f"ci.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = ${idx})")
                params.append(str(course_id))
                idx += 1

            where = " AND ".join(conditions)
            keyword_rows = await conn.fetch(
                f"""SELECT ci.id, ci.title,
                           LEFT(ci.body_md, 200) AS snippet,
                           1.0 AS score
                    FROM content_items ci
                    WHERE {where}
                    LIMIT ${idx}""",
                *params, top_k,
            )

            results = [
                {"id": str(r["id"]), "title": r["title"], "snippet": r["snippet"] or "", "score": float(r["score"])}
                for r in keyword_rows
            ]

            # Step 2: if keyword results < top_k, supplement with semantic search
            if len(results) < top_k and query:
                query_vec = embed_text(query)
                remaining = top_k - len(results)
                seen_ids = {r["id"] for r in results}

                sem_conditions = ["n.embedding IS NOT NULL"]
                sem_params: list[Any] = [str(query_vec)]
                sem_idx = 2

                if course_id:
                    sem_conditions.append(f"n.metadata->>'course_id' = ${sem_idx}")
                    sem_params.append(str(course_id))
                    sem_idx += 1

                sem_where = " AND ".join(sem_conditions)
                sem_rows = await conn.fetch(
                    f"""SELECT ci.id, ci.title,
                               LEFT(ci.body_md, 200) AS snippet,
                               1 - (n.embedding <=> $1::vector) AS score
                        FROM content_items ci
                        JOIN nodes n ON n.id = ci.node_id
                        WHERE {sem_where}
                        ORDER BY n.embedding <=> $1::vector
                        LIMIT ${sem_idx}""",
                    *sem_params, remaining + len(seen_ids),  # fetch extra to account for dedup
                )

                for r in sem_rows:
                    rid = str(r["id"])
                    if rid not in seen_ids:
                        results.append({
                            "id": rid,
                            "title": r["title"],
                            "snippet": r["snippet"] or "",
                            "score": round(float(r["score"]), 4),
                        })
                        seen_ids.add(rid)
                        if len(results) >= top_k:
                            break

            # Sort by score descending
            results.sort(key=lambda r: r["score"], reverse=True)
            return {"results": results[:top_k]}

    async def save_draft(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args.get("node_id")
        kind = args["kind"]
        title = args["title"]
        body_md = args["body_md"]
        author_id = args["author_id"]

        async with pool.acquire() as conn:
            draft_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO content_items (id, node_id, kind, title, body_md, author_id, is_draft)
                   VALUES ($1, $2, $3, $4, $5, $6, true)""",
                draft_id,
                uuid.UUID(node_id) if node_id else None,
                kind, title, body_md, uuid.UUID(author_id),
            )
            return {"draft_id": str(draft_id)}

    async def library_search(args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        kind = args.get("kind")
        top_k = args.get("top_k", 10)

        async with pool.acquire() as conn:
            conditions = ["ci.title ILIKE $1"]
            params: list[Any] = [f"%{query}%"]
            idx = 2

            if kind:
                conditions.append(f"ci.kind = ${idx}")
                params.append(kind)
                idx += 1

            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"""SELECT ci.id, ci.kind, ci.title,
                           LEFT(ci.body_md, 200) AS snippet
                    FROM content_items ci
                    WHERE {where}
                    LIMIT ${idx}""",
                *params, top_k,
            )
            return {
                "items": [
                    {"id": str(r["id"]), "kind": r["kind"], "title": r["title"], "snippet": r["snippet"] or ""}
                    for r in rows
                ]
            }

    async def list_modules(args: dict[str, Any]) -> dict[str, Any]:
        course_id = args["course_id"]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT m.module_id AS id, m.title,
                          (m.metadata->>'order')::int AS "order"
                   FROM modules m
                   WHERE m.course_id = $1
                   ORDER BY (m.metadata->>'order')::int NULLS LAST""",
                uuid.UUID(course_id),
            )
            return {
                "modules": [
                    {"id": str(r["id"]), "title": r["title"], "order": r["order"]}
                    for r in rows
                ]
            }

    return [
        ToolDef(
            name="content.retrieve",
            description="Retrieve content item by node_id or content_id",
            input_schema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "content_id": {"type": "string"},
                },
            },
            handler=retrieve,
        ),
        ToolDef(
            name="content.search",
            description="Search content by query string",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "course_id": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=search,
        ),
        ToolDef(
            name="content.save_draft",
            description="Save a draft content item",
            input_schema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "title": {"type": "string"},
                    "body_md": {"type": "string"},
                    "author_id": {"type": "string"},
                },
                "required": ["kind", "title", "body_md", "author_id"],
            },
            handler=save_draft,
            mutates=True,
        ),
        ToolDef(
            name="content.library_search",
            description="Search the content library",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
            },
            handler=library_search,
        ),
        ToolDef(
            name="content.list_modules",
            description="List modules for a course",
            input_schema={
                "type": "object",
                "properties": {"course_id": {"type": "string"}},
                "required": ["course_id"],
            },
            handler=list_modules,
        ),
    ]
