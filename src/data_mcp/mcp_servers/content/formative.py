"""Content-server tools for the formative loop: targeted practice sets (spec.md §7.4) and the
outcome subgraph used for syllabus-aware alignment (spec.md §7.6)."""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base.server import ToolHandler
from data_mcp.mcp_servers._args import (
    forbidden,
    is_int,
    not_found,
    text_arg,
    uuid_arg,
    uuid_list,
)
from data_mcp.mcp_servers._helpers import validation_error

PRACTICE_MIN = 3
PRACTICE_MAX = 5
QUESTION_TYPES = frozenset({"mcq", "short_answer", "essay", "code"})
BLOOM_LEVELS = frozenset({"remember", "understand", "apply", "analyze", "evaluate", "create"})
DIFFICULTIES = frozenset({"easy", "medium", "hard"})
PRACTICE_BANK_KIND = "practice"

SUBGRAPH_DEPTH_DEFAULT = 2
SUBGRAPH_DEPTH_MAX = 4
SUBGRAPH_MAX_OUTCOMES = 20
SUBGRAPH_MAX_NODES = 500
# Traversal never passes through a course or program node, so one outcome cannot pull in
# the whole course.
SUBGRAPH_NODE_KINDS = ["outcome", "concept", "module", "assessment_item"]
SUBGRAPH_EDGE_KINDS = ["aligned_with", "part_of", "contributes_to"]


def _parse_items(raw: Any, count: Any) -> list[dict[str, Any]]:
    if not is_int(count) or not PRACTICE_MIN <= count <= PRACTICE_MAX:
        raise ValueError(f"count must be an integer from {PRACTICE_MIN} to {PRACTICE_MAX}")
    if not isinstance(raw, list) or len(raw) != count:
        raise ValueError("items must list exactly count items")
    items: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be an object")
        q_type = item.get("type")
        if q_type not in QUESTION_TYPES:
            raise ValueError(f"items[{i}].type must be one of {sorted(QUESTION_TYPES)}")
        options = item.get("options")
        if options is not None and not isinstance(options, dict):
            raise ValueError(f"items[{i}].options must be an object")
        if q_type == "mcq" and not options:
            raise ValueError(f"items[{i}] is mcq and needs options")
        answer_key = item.get("answer_key")
        if not isinstance(answer_key, dict) or not answer_key:
            raise ValueError(f"items[{i}].answer_key must be a non-empty object")
        bloom = item.get("bloom_level")
        if bloom not in BLOOM_LEVELS:
            raise ValueError(f"items[{i}].bloom_level must be one of {sorted(BLOOM_LEVELS)}")
        difficulty = item.get("difficulty")
        if difficulty is not None and difficulty not in DIFFICULTIES:
            raise ValueError(f"items[{i}].difficulty must be one of {sorted(DIFFICULTIES)}")
        items.append({
            "type": q_type, "stem": text_arg(item.get("stem"), f"items[{i}].stem"),
            "options": options, "answer_key": answer_key, "bloom_level": bloom,
            "difficulty": difficulty,
        })
    return items


def formative_content_handlers(pool: asyncpg.Pool) -> dict[str, ToolHandler]:
    """Handlers by tool name; tools.py declares their ToolDefs (the contract check reads it)."""

    async def generate_practice(args: dict[str, Any]) -> dict[str, Any]:
        try:
            criterion_id = uuid_arg(args, "criterion_id", required=True)
            student_id = uuid_arg(args, "student_id", required=True)
            items = _parse_items(args.get("items"), args.get("count"))
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn:
            criterion = await conn.fetchrow(
                """SELECT rc.id, rc.key, rc.rubric_id, rc.outcome_nodes,
                          a.metadata->>'course_id' AS course
                   FROM rubric_criteria rc
                   JOIN nodes a ON a.kind = 'assessment_item'
                    AND a.metadata->>'rubric_id' = rc.rubric_id::text
                   WHERE rc.id = $1
                   ORDER BY a.id LIMIT 1""",
                criterion_id,
            )
            if criterion is None:
                return not_found("Criterion not found on any assignment's rubric")
            try:
                course_id = uuid.UUID(criterion["course"] or "")
            except ValueError:
                return not_found("The criterion's assignment is not attached to a course")
            enrolled = await conn.fetchval(
                """SELECT 1 FROM enrollments WHERE person_id = $1 AND course_node = $2
                   AND role = 'student' AND status = 'active'""",
                student_id, course_id,
            )
            if not enrolled:
                return forbidden("Practice is generated only for a student in the course")
            aligned = list(criterion["outcome_nodes"] or [])
            question_ids = [uuid.uuid4() for _ in items]
            practice_set_id = uuid.uuid4()
            async with conn.transaction():
                bank_id = await _practice_bank(conn, course_id)
                await conn.execute(
                    """INSERT INTO ai_actions (id, agent, action_type, subject_person,
                                               course_node, target_type, target_id, sources,
                                               output)
                       VALUES ($1, 'content_generator', 'practice_item', $2, $3,
                               'question_banks', $4, $5, $6)""",
                    practice_set_id, student_id, course_id, bank_id,
                    json.dumps([{"type": "rubric", "id": str(criterion["rubric_id"])},
                                *({"type": "node", "id": str(n)} for n in aligned)]),
                    json.dumps({
                        "practice_set_id": str(practice_set_id),
                        "criterion_id": str(criterion_id),
                        "criterion_key": criterion["key"],
                        "question_ids": [str(q) for q in question_ids],
                        "aligned_nodes": [str(n) for n in aligned],
                        "items": items,
                    }),
                )
                await conn.executemany(
                    """INSERT INTO questions (id, bank_id, type, stem, options, answer_key,
                                              bloom_level, difficulty, aligned_nodes, metadata)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    [(qid, bank_id, item["type"], item["stem"],
                      json.dumps(item["options"]) if item["options"] is not None else None,
                      json.dumps(item["answer_key"]), item["bloom_level"], item["difficulty"],
                      aligned,
                      json.dumps({"practice_set_id": str(practice_set_id),
                                  "student_id": str(student_id),
                                  "criterion_id": str(criterion_id),
                                  "visibility": "private"}))
                     for qid, item in zip(question_ids, items, strict=True)],
                )
        return {
            "practice_set_id": str(practice_set_id),
            "question_ids": [str(q) for q in question_ids],
            "aligned_nodes": [str(n) for n in aligned],
            "bank_id": str(bank_id),
        }

    async def subgraph_for_outcomes(args: dict[str, Any]) -> dict[str, Any]:
        try:
            outcome_ids = uuid_list(args.get("outcome_ids"), "outcome_ids",
                                     max_items=SUBGRAPH_MAX_OUTCOMES)
            if not outcome_ids:
                raise ValueError("outcome_ids must name at least one outcome")
            depth = args.get("depth", SUBGRAPH_DEPTH_DEFAULT)
            if not is_int(depth) or not 1 <= depth <= SUBGRAPH_DEPTH_MAX:
                raise ValueError(f"depth must be an integer from 1 to {SUBGRAPH_DEPTH_MAX}")
        except ValueError as exc:
            return {**validation_error(str(exc)), "nodes": [], "edges": []}

        async with pool.acquire() as conn:
            found = await conn.fetch(
                """SELECT id FROM nodes WHERE id = ANY($1::uuid[])
                   AND kind IN ('outcome', 'program_outcome')""",
                outcome_ids,
            )
            known = {r["id"] for r in found}
            unknown = [str(o) for o in outcome_ids if o not in known]
            if unknown:
                return {**validation_error(f"{unknown[0]} is not an outcome node"),
                        "nodes": [], "edges": []}
            visited: set[uuid.UUID] = set(outcome_ids)
            frontier = list(outcome_ids)
            edges: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
            for _ in range(depth):
                if not frontier or len(visited) >= SUBGRAPH_MAX_NODES:
                    break
                rows = await conn.fetch(
                    """SELECT e.from_node, e.to_node, e.kind::text AS kind
                       FROM edges e
                       JOIN nodes f ON f.id = e.from_node
                       JOIN nodes t ON t.id = e.to_node
                       WHERE (e.from_node = ANY($1::uuid[]) OR e.to_node = ANY($1::uuid[]))
                         AND e.kind::text = ANY($2::text[])
                         AND f.kind::text = ANY($3::text[]) AND t.kind::text = ANY($3::text[])
                       ORDER BY e.from_node, e.to_node, e.kind""",
                    frontier, SUBGRAPH_EDGE_KINDS, SUBGRAPH_NODE_KINDS + ["program_outcome"],
                )
                nxt: list[uuid.UUID] = []
                for r in rows:
                    for node in (r["from_node"], r["to_node"]):
                        if node not in visited and len(visited) < SUBGRAPH_MAX_NODES:
                            visited.add(node)
                            nxt.append(node)
                    if r["from_node"] in visited and r["to_node"] in visited:
                        edges.add((r["from_node"], r["to_node"], r["kind"]))
                frontier = nxt
            nodes = await conn.fetch(
                """SELECT id, title, kind::text AS kind FROM nodes
                   WHERE id = ANY($1::uuid[]) ORDER BY kind, title, id""",
                list(visited),
            )
        return {
            "nodes": [{"id": str(n["id"]), "title": n["title"], "kind": n["kind"]}
                      for n in nodes],
            "edges": [{"src": str(a), "dst": str(b), "kind": k}
                      for a, b, k in sorted(edges, key=lambda e: (str(e[0]), str(e[1]), e[2]))],
            "truncated": len(visited) >= SUBGRAPH_MAX_NODES,
        }

    return {
        "content.generate_practice": generate_practice,
        "graph.subgraph_for_outcomes": subgraph_for_outcomes,
    }


async def _practice_bank(conn: asyncpg.Connection, course_id: uuid.UUID) -> uuid.UUID:
    """The course's private practice bank, created on first use. Call inside a transaction."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                       f"practice-bank:{course_id}")
    bank = await conn.fetchval(
        """SELECT id FROM question_banks
           WHERE course_node = $1 AND metadata->>'kind' = $2 ORDER BY id LIMIT 1""",
        course_id, PRACTICE_BANK_KIND,
    )
    if bank is not None:
        return bank
    title = await conn.fetchval("SELECT title FROM nodes WHERE id = $1", course_id)
    return await conn.fetchval(
        """INSERT INTO question_banks (course_node, title, metadata)
           VALUES ($1, $2, $3) RETURNING id""",
        course_id, f"{title or 'Course'} practice (private)",
        json.dumps({"kind": PRACTICE_BANK_KIND}),
    )
