"""Content MCP server tool handlers."""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef
from data_mcp.mcp_servers._helpers import resolve_concept_id, validation_error
from data_mcp.mcp_servers.content.formative import (
    BLOOM_LEVELS,
    DIFFICULTIES,
    formative_content_handlers,
)

# Values of the edge_kind enum in contracts/db-schema.sql.
EDGE_KINDS = frozenset({
    "prerequisite_of", "part_of", "evidence_of", "aligned_with", "variant_of", "contributes_to",
})

# Contract spelling ("in"/"out") and the server's original spelling both accepted.
_NEIGHBOR_DIRECTIONS = {
    "both": "both", "incoming": "incoming", "outgoing": "outgoing", "in": "incoming", "out": "outgoing",
}


def _parse_edge_kinds(raw: Any) -> list[str] | None:
    """Normalise a kinds argument (a string, comma-separated string or list) to a validated list.

    Returns None when no filter was given. Raises ValueError on any value outside EDGE_KINDS.
    """
    if raw is None or raw == "" or raw == []:
        return None
    if isinstance(raw, str):
        values = [v.strip() for v in raw.split(",") if v.strip()]
    elif isinstance(raw, list) and all(isinstance(v, str) for v in raw):
        values = [v.strip() for v in raw]
    else:
        raise ValueError("kinds must be a string or a list of strings")
    invalid = [v for v in values if v not in EDGE_KINDS]
    if invalid or not values:
        raise ValueError(f"invalid edge kind(s) {invalid!r}; allowed: {sorted(EDGE_KINDS)}")
    return values


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all content server tool definitions."""
    formative = formative_content_handlers(pool)

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
                       ORDER BY ci.created_at DESC, ci.id DESC LIMIT 1""",
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
            keyword_rows = await conn.fetch(
                """SELECT ci.id, ci.title,
                          LEFT(ci.body_md, 200) AS snippet,
                          1.0 AS score
                   FROM content_items ci
                   WHERE (ci.title ILIKE $1 OR ci.body_md ILIKE $1)
                     AND ($2::text IS NULL
                          OR ci.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = $2))
                   ORDER BY ci.title, ci.id
                   LIMIT $3""",
                f"%{query}%", str(course_id) if course_id else None, top_k,
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

                sem_rows = await conn.fetch(
                    """SELECT ci.id, ci.title,
                              LEFT(ci.body_md, 200) AS snippet,
                              1 - (n.embedding <=> $1::vector) AS score
                       FROM content_items ci
                       JOIN nodes n ON n.id = ci.node_id
                       WHERE n.embedding IS NOT NULL
                         AND ($2::text IS NULL OR n.metadata->>'course_id' = $2)
                       ORDER BY n.embedding <=> $1::vector, ci.title, ci.id
                       LIMIT $3""",
                    str(query_vec),
                    str(course_id) if course_id else None,
                    remaining + len(seen_ids),  # fetch extra to account for dedup
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
            rows = await conn.fetch(
                """SELECT ci.id, ci.kind, ci.title,
                          LEFT(ci.body_md, 200) AS snippet
                   FROM content_items ci
                   WHERE ci.title ILIKE $1
                     AND ($2::text IS NULL OR ci.kind = $2)
                   LIMIT $3""",
                f"%{query}%", kind or None, top_k,
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
        if not node_id:
            return {"error": "node_id is required"}
        raw_direction = args.get("direction") or "both"
        direction = _NEIGHBOR_DIRECTIONS.get(raw_direction) if isinstance(raw_direction, str) else None
        if direction is None:
            return validation_error(
                f"direction must be one of {sorted(_NEIGHBOR_DIRECTIONS)}"
            )
        try:
            kinds = _parse_edge_kinds(args.get("kinds"))
        except ValueError as exc:
            return validation_error(str(exc))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT e.to_node AS nid, e.kind AS ek FROM edges e
                   WHERE e.from_node = $1 AND $2::boolean
                     AND ($4::text[] IS NULL OR e.kind = ANY($4::text[]::edge_kind[]))
                   UNION
                   SELECT e.from_node AS nid, e.kind AS ek FROM edges e
                   WHERE e.to_node = $1 AND $3::boolean
                     AND ($4::text[] IS NULL OR e.kind = ANY($4::text[]::edge_kind[]))
                   ORDER BY nid, ek""",
                uuid.UUID(node_id),
                direction in ("outgoing", "both"),
                direction in ("incoming", "both"),
                kinds,
            )
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
                    att = await conn.fetchrow("SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 AND level IN ('proficient', 'mastery')", uuid.UUID(person_id), r["id"])
                    satisfied = att is not None
                prerequisites.append({"id": str(r["id"]), "title": r["title"], "kind": r["kind"], "satisfied": satisfied})
            return {"prerequisites": prerequisites}

    async def get_skill(args: dict[str, Any]) -> dict[str, Any]:
        concept_id = args.get("concept_id")
        person_id = args.get("person_id")
        if not concept_id:
            return {"error": "concept_id is required"}
        async with pool.acquire() as conn:
            cid = await resolve_concept_id(conn, concept_id)
            if cid is None:
                return {"error": f"Concept not found: {concept_id}"}

            # Fetch skill content
            row = await conn.fetchrow(
                """SELECT ci.body_md, n.title as concept_title
                   FROM content_items ci JOIN nodes n ON n.id = ci.node_id
                   WHERE ci.node_id = $1 AND ci.kind = 'skill'""", cid)
            if not row:
                return {"error": "No skill content for this concept", "concept_id": str(cid)}

            result: dict[str, Any] = {
                "id": str(cid),
                "concept_title": row["concept_title"],
                "body_md": row["body_md"],
            }

            # Prerequisite soft gate: check gaps if person_id provided
            if person_id:
                prereqs = await conn.fetch(
                    """SELECT n.id, n.title FROM edges e
                       JOIN nodes n ON n.id = e.from_node
                       WHERE e.to_node = $1 AND e.kind = 'prerequisite_of'""", cid)
                gaps = []
                for p in prereqs:
                    att = await conn.fetchrow(
                        "SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 ORDER BY issued_at DESC LIMIT 1",
                        uuid.UUID(person_id), p["id"])
                    student_level = att["level"] if att else "not_started"
                    if student_level not in ("proficient", "mastery"):
                        gaps.append({
                            "id": str(p["id"]),
                            "title": p["title"],
                            "required_level": "proficient",
                            "student_level": student_level,
                        })
                if gaps:
                    result["prerequisite_gaps"] = gaps

            return result

    async def save_skill_handler(args: dict[str, Any]) -> dict[str, Any]:
        concept_id = args.get("concept_id")
        body_md = args.get("body_md")
        author_id = args.get("author_id")
        if not concept_id or not body_md:
            return {"error": "concept_id and body_md are required"}
        async with pool.acquire() as conn:
            cid = uuid.UUID(concept_id)
            aid = uuid.UUID(author_id) if author_id else None
            concept = await conn.fetchrow("SELECT title FROM nodes WHERE id = $1", cid)
            if not concept:
                return {"error": "Concept not found"}
            existing = await conn.fetchrow("SELECT id FROM content_items WHERE node_id = $1 AND kind = 'skill'", cid)
            if existing:
                await conn.execute("UPDATE content_items SET body_md = $1, author_id = $2 WHERE id = $3", body_md, aid, existing["id"])
                return {"id": str(existing["id"]), "updated": True}
            else:
                new_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO content_items (id, node_id, kind, title, body_md, author_id) VALUES ($1, $2, 'skill', $3, $4, $5)",
                    new_id, cid, f"Skill: {concept['title']}", body_md, aid)
                return {"id": str(new_id), "created": True}

    async def list_skills(args: dict[str, Any]) -> dict[str, Any]:
        course_id = args.get("course_id")
        if not course_id:
            return {"error": "course_id is required"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.id as concept_id, c.title as concept_title, m.title as module_title,
                          ci.id IS NOT NULL as has_skill, COALESCE(length(ci.body_md), 0) as char_count
                   FROM modules mod
                   JOIN edges e ON e.to_node = mod.module_id AND e.kind = 'part_of'
                   JOIN nodes c ON c.id = e.from_node AND c.kind = 'concept'
                   JOIN nodes m ON m.id = mod.module_id
                   LEFT JOIN content_items ci ON ci.node_id = c.id AND ci.kind = 'skill'
                   WHERE mod.course_id = $1
                   ORDER BY (mod.metadata->>'order')::int, c.title""",
                uuid.UUID(course_id))
            return {"skills": [
                {"concept_id": str(r["concept_id"]), "concept_title": r["concept_title"],
                 "module_title": r["module_title"], "has_skill": r["has_skill"],
                 "word_count": r["char_count"] // 5 if r["char_count"] else 0}
                for r in rows
            ]}

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
                "node_id": {"type": "string"}, "direction": {"type": "string", "enum": sorted(_NEIGHBOR_DIRECTIONS)},
                "depth": {"type": "integer"},
                "kinds": {
                    "description": "Edge kind, comma-separated kinds, or a list of kinds",
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string", "enum": sorted(EDGE_KINDS)}},
                    ],
                },
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
        ToolDef(
            name="content.get_skill",
            description="Get the skill document for a concept — includes prerequisite gap warnings if person_id provided",
            input_schema={"type": "object", "properties": {
                "concept_id": {"type": "string"},
                "person_id": {"type": "string"},
            }, "required": ["concept_id"]},
            handler=get_skill,
            mutates=False,
        ),
        ToolDef(
            name="content.save_skill",
            description="Create or update skill content for a concept",
            input_schema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                    "body_md": {"type": "string"},
                    "author_id": {"type": "string"},
                },
                "required": ["concept_id", "body_md"],
            },
            handler=save_skill_handler,
            mutates=True,
            requires_approval=False,
        ),
        ToolDef(
            name="content.list_skills",
            description="List all concepts in a course with their skill content status",
            input_schema={
                "type": "object",
                "properties": {"course_id": {"type": "string"}},
                "required": ["course_id"],
            },
            handler=list_skills,
            mutates=False,
        ),
        ToolDef(
            name="content.generate_practice",
            description=(
                "Save a targeted practice set (3-5 items the agent wrote) for one student and "
                "one rubric criterion; items are aligned to the criterion's outcomes"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "criterion_id": {"type": "string"},
                    "student_id": {"type": "string"},
                    "count": {"type": "integer"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string",
                                         "enum": ["mcq", "short_answer", "essay", "code"]},
                                "stem": {"type": "string"},
                                "options": {"type": "object"},
                                "answer_key": {"type": "object"},
                                "bloom_level": {"type": "string", "enum": sorted(BLOOM_LEVELS)},
                                "difficulty": {"type": "string", "enum": sorted(DIFFICULTIES)},
                            },
                            "required": ["type", "stem", "answer_key", "bloom_level"],
                        },
                    },
                },
                "required": ["criterion_id", "student_id", "count", "items"],
            },
            handler=formative["content.generate_practice"],
            mutates=True,
        ),
        ToolDef(
            name="graph.subgraph_for_outcomes",
            description=(
                "Concepts, modules and assessments linked to the given outcomes over "
                "aligned_with, part_of and contributes_to edges"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "outcome_ids": {"type": "array", "items": {"type": "string"}},
                    "depth": {"type": "integer"},
                },
                "required": ["outcome_ids"],
            },
            handler=formative["graph.subgraph_for_outcomes"],
        ),
    ]
