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

    async def graph_neighbors(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args.get("node_id")
        direction = args.get("direction", "both")
        kind_filter = args.get("kinds")
        if not node_id:
            return {"error": "node_id is required"}
        async with pool.acquire() as conn:
            nid = uuid.UUID(node_id)
            queries = []
            if direction in ("outgoing", "both"):
                q = "SELECT e.to_node AS nid, e.kind AS ek FROM edges e WHERE e.from_node = $1"
                if kind_filter: q += f" AND e.kind = '{kind_filter}'"
                queries.append(q)
            if direction in ("incoming", "both"):
                q = "SELECT e.from_node AS nid, e.kind AS ek FROM edges e WHERE e.to_node = $1"
                if kind_filter: q += f" AND e.kind = '{kind_filter}'"
                queries.append(q)
            rows = await conn.fetch(" UNION ".join(queries), nid)
            nodes = []
            for r in rows:
                node = await conn.fetchrow("SELECT id, title, kind FROM nodes WHERE id = $1", r["nid"])
                if node:
                    nodes.append({"id": str(node["id"]), "title": node["title"], "kind": node["kind"], "edge_kind": r["ek"]})
            return {"nodes": nodes}

    async def graph_prerequisites(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args.get("node_id")
        person_id = args.get("person_id")
        if not node_id:
            return {"error": "node_id is required"}
        async with pool.acquire() as conn:
            nid = uuid.UUID(node_id)
            rows = await conn.fetch(
                "SELECT n.id, n.title, n.kind FROM edges e JOIN nodes n ON n.id = e.from_node WHERE e.to_node = $1 AND e.kind = 'prerequisite_of'", nid)
            prerequisites = []
            for r in rows:
                satisfied = False
                if person_id:
                    att = await conn.fetchrow("SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 AND level = 'mastery'", uuid.UUID(person_id), r["id"])
                    satisfied = att is not None
                prerequisites.append({"id": str(r["id"]), "title": r["title"], "kind": r["kind"], "satisfied": satisfied})
            return {"prerequisites": prerequisites}

    async def graph_mastery_map(args: dict[str, Any]) -> dict[str, Any]:
        person_id_str = args.get("person_id")
        course_id_str = args.get("course_id")
        if not person_id_str or not course_id_str:
            return {"error": "person_id and course_id are required"}
        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id_str)
            cid = uuid.UUID(course_id_str)
            person = await conn.fetchrow("SELECT display_name FROM persons WHERE id = $1", pid)
            student_name = person["display_name"] if person else "Unknown"
            course = await conn.fetchrow("SELECT title FROM nodes WHERE id = $1 AND kind = 'course'", cid)
            course_title = course["title"] if course else "Unknown"

            mc_rows = await conn.fetch(
                "SELECT id, title FROM nodes WHERE kind = 'microcredential' AND metadata->>'course_id' = $1 ORDER BY title", str(cid))

            total_m = total_p = total_e = total_ns = total_c = mc_earned = 0
            microcredentials = []
            for mc in mc_rows:
                mod_rows = await conn.fetch(
                    """SELECT n.id, n.title FROM edges e JOIN nodes n ON n.id = e.from_node
                       WHERE e.to_node = $1 AND e.kind = 'contributes_to' AND n.kind = 'module'
                       ORDER BY (n.metadata->>'order')::int NULLS LAST""", mc["id"])
                mc_m = mc_p = mc_e = mc_ns = mc_t = 0
                modules = []
                for mod in mod_rows:
                    concept_rows = await conn.fetch(
                        """SELECT n.id, n.title FROM edges e JOIN nodes n ON n.id = e.from_node
                           WHERE e.to_node = $1 AND e.kind = 'part_of' AND n.kind = 'concept' ORDER BY n.title""", mod["id"])
                    concepts = []
                    for c in concept_rows:
                        att = await conn.fetchrow(
                            "SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 ORDER BY issued_at DESC LIMIT 1", pid, c["id"])
                        level = att["level"] if att else "not_started"
                        if level == "mastery": mc_m += 1
                        elif level == "proficient": mc_p += 1
                        elif level == "emerging": mc_e += 1
                        else: mc_ns += 1
                        mc_t += 1
                        concepts.append({"id": str(c["id"]), "title": c["title"], "level": level})
                    modules.append({"id": str(mod["id"]), "title": mod["title"], "concepts": concepts})
                earned = mc_m == mc_t and mc_t > 0
                if earned: mc_earned += 1
                total_m += mc_m; total_p += mc_p; total_e += mc_e; total_ns += mc_ns; total_c += mc_t
                microcredentials.append({
                    "id": str(mc["id"]), "title": mc["title"], "earned": earned,
                    "progress": {"mastery": mc_m, "proficient": mc_p, "emerging": mc_e, "not_started": mc_ns},
                    "total_concepts": mc_t, "modules": modules,
                })
            return {
                "student_name": student_name, "course_title": course_title,
                "microcredentials": microcredentials,
                "summary": {
                    "total_concepts": total_c, "mastery": total_m, "proficient": total_p,
                    "emerging": total_e, "not_started": total_ns,
                    "microcredentials_earned": mc_earned, "microcredentials_total": len(microcredentials),
                },
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
        ToolDef(
            name="graph.neighbors",
            description="Get neighboring nodes in the knowledge graph by edge direction and kind",
            input_schema={"type": "object", "properties": {
                "node_id": {"type": "string"}, "direction": {"type": "string", "enum": ["both", "incoming", "outgoing"]},
                "depth": {"type": "integer"}, "kinds": {"type": "string"},
            }, "required": ["node_id"]},
            handler=graph_neighbors, mutates=False,
        ),
        ToolDef(
            name="graph.prerequisites",
            description="Get prerequisites for a node, optionally checking if a student has satisfied them",
            input_schema={"type": "object", "properties": {
                "node_id": {"type": "string"}, "person_id": {"type": "string"},
            }, "required": ["node_id"]},
            handler=graph_prerequisites, mutates=False,
        ),
        ToolDef(
            name="graph.mastery_map",
            description="Get the full mastery state for a student in a course: microcredentials, concepts, attestation levels",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"},
            }, "required": ["person_id", "course_id"]},
            handler=graph_mastery_map, mutates=False,
        ),
    ]
