"""Assessments MCP server tool handlers."""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all assessments server tool definitions."""

    async def create_question(args: dict[str, Any]) -> dict[str, Any]:
        bank_id = args["bank_id"]
        q_type = args["type"]
        stem = args["stem"]
        options = args.get("options")
        answer_key = args["answer_key"]
        bloom_level = args.get("bloom_level")
        difficulty = args.get("difficulty")
        aligned_nodes = args.get("aligned_nodes", [])

        async with pool.acquire() as conn:
            # Verify bank exists
            bank = await conn.fetchrow(
                "SELECT id FROM question_banks WHERE id = $1",
                uuid.UUID(bank_id),
            )
            if not bank:
                return {"error": "Question bank not found"}

            question_id = uuid.uuid4()
            import json as _json
            aligned_uuids = [uuid.UUID(n) for n in aligned_nodes] if aligned_nodes else []
            await conn.execute(
                """INSERT INTO questions
                   (id, bank_id, type, stem, options, answer_key, bloom_level, difficulty, aligned_nodes)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                question_id,
                uuid.UUID(bank_id),
                q_type,
                stem,
                _json.dumps(options) if options is not None else None,
                _json.dumps(answer_key),
                bloom_level,
                difficulty,
                aligned_uuids,
            )
            return {"question_id": str(question_id)}

    async def search_bank(args: dict[str, Any]) -> dict[str, Any]:
        bank_id = args.get("bank_id")
        query = args.get("query", "")
        aligned_nodes = args.get("aligned_nodes")

        async with pool.acquire() as conn:
            conditions: list[str] = []
            params: list[Any] = []
            idx = 1

            if bank_id:
                conditions.append(f"q.bank_id = ${idx}")
                params.append(uuid.UUID(bank_id))
                idx += 1

            if query:
                conditions.append(f"q.stem ILIKE ${idx}")
                params.append(f"%{query}%")
                idx += 1

            if aligned_nodes:
                node_uuids = [uuid.UUID(n) for n in aligned_nodes]
                conditions.append(f"q.aligned_nodes && ${idx}::uuid[]")
                params.append(node_uuids)
                idx += 1

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = await conn.fetch(
                f"""SELECT q.id, q.type, q.stem, q.options, q.bloom_level, q.difficulty, q.aligned_nodes
                    FROM questions q
                    {where}
                    LIMIT 50""",
                *params,
            )
            return {
                "questions": [
                    {
                        "id": str(r["id"]),
                        "type": r["type"],
                        "stem": r["stem"],
                        "options": r["options"],
                        "bloom_level": r["bloom_level"],
                        "difficulty": r["difficulty"],
                        "aligned_nodes": [str(n) for n in r["aligned_nodes"]] if r["aligned_nodes"] else [],
                    }
                    for r in rows
                ]
            }

    async def get_submission(args: dict[str, Any]) -> dict[str, Any]:
        submission_id = args["submission_id"]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, person_id, assignment_node, body_md, attachments, submitted_at
                   FROM submissions WHERE id = $1""",
                uuid.UUID(submission_id),
            )
            if not row:
                return {"error": "Submission not found"}
            return {
                "id": str(row["id"]),
                "person_id": str(row["person_id"]),
                "assignment_node": str(row["assignment_node"]),
                "body_md": row["body_md"] or "",
                "attachments": row["attachments"],
                "submitted_at": row["submitted_at"].isoformat(),
            }

    async def get_rubric(args: dict[str, Any]) -> dict[str, Any]:
        import json as _json
        rubric_id = args["rubric_id"]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, title, criteria FROM rubrics WHERE id = $1",
                uuid.UUID(rubric_id),
            )
            if not row:
                return {"error": "Rubric not found"}
            criteria = row["criteria"]
            if isinstance(criteria, str):
                criteria = _json.loads(criteria)
            return {
                "id": str(row["id"]),
                "title": row["title"],
                "criteria": criteria,
            }

    async def draft_grade(args: dict[str, Any]) -> dict[str, Any]:
        submission_id = args["submission_id"]
        rubric_id = args.get("rubric_id")
        scores = args["scores"]
        feedback = args["feedback"]
        holistic_md = args.get("holistic_md")
        graded_by = args["graded_by"]

        import json as _json
        async with pool.acquire() as conn:
            # Verify submission exists
            sub = await conn.fetchrow(
                "SELECT id FROM submissions WHERE id = $1",
                uuid.UUID(submission_id),
            )
            if not sub:
                return {"error": "Submission not found"}

            grade_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO grades
                   (id, submission_id, rubric_id, scores, feedback, holistic_md, graded_by, is_draft)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, true)""",
                grade_id,
                uuid.UUID(submission_id),
                uuid.UUID(rubric_id) if rubric_id else None,
                _json.dumps(scores),
                _json.dumps(feedback),
                holistic_md,
                uuid.UUID(graded_by),
            )
            return {"grade_id": str(grade_id)}

    async def commit_grade(args: dict[str, Any]) -> dict[str, Any]:
        grade_id = args["grade_id"]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, is_draft FROM grades WHERE id = $1",
                uuid.UUID(grade_id),
            )
            if not row:
                return {"error": "Grade not found"}
            if not row["is_draft"]:
                return {"error": "Grade is already committed"}

            committed_at = await conn.fetchval(
                """UPDATE grades SET is_draft = false, committed_at = now()
                   WHERE id = $1 RETURNING committed_at""",
                uuid.UUID(grade_id),
            )
            return {
                "committed": True,
                "committed_at": committed_at.isoformat(),
            }

    async def attest(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        node_id = args.get("node_id")
        level = args.get("level")
        issuer_id = args.get("issuer_id")
        if not person_id or not node_id or not level:
            return {"error": "person_id, node_id, and level are required"}
        if level not in ("emerging", "proficient", "mastery"):
            return {"error": "level must be emerging, proficient, or mastery"}
        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id)
            nid = uuid.UUID(node_id)
            iid = uuid.UUID(issuer_id) if issuer_id else None
            existing = await conn.fetchrow(
                "SELECT id, level FROM attestations WHERE person_id = $1 AND node_id = $2", pid, nid)
            if existing:
                await conn.execute(
                    "UPDATE attestations SET level = $1, issuer_id = $2, issued_at = now() WHERE id = $3",
                    level, iid, existing["id"])
                return {"attestation_id": str(existing["id"]), "updated": True, "previous_level": existing["level"]}
            else:
                att_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO attestations (id, person_id, node_id, level, issuer_id) VALUES ($1, $2, $3, $4, $5)",
                    att_id, pid, nid, level, iid)
                return {"attestation_id": str(att_id), "created": True}

    async def get_student_attestations(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        if not person_id:
            return {"error": "person_id is required"}
        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id)
            if course_id:
                rows = await conn.fetch(
                    """SELECT a.node_id, n.title AS node_title, a.level, a.issued_at
                       FROM attestations a
                       JOIN nodes n ON n.id = a.node_id
                       JOIN edges e1 ON e1.from_node = n.id AND e1.kind = 'part_of'
                       JOIN edges e2 ON e2.from_node = e1.to_node AND e2.kind = 'part_of'
                       WHERE a.person_id = $1 AND e2.to_node = $2
                       ORDER BY a.issued_at DESC""", pid, uuid.UUID(course_id))
            else:
                rows = await conn.fetch(
                    """SELECT a.node_id, n.title AS node_title, a.level, a.issued_at
                       FROM attestations a JOIN nodes n ON n.id = a.node_id
                       WHERE a.person_id = $1 ORDER BY a.issued_at DESC""", pid)
            return {"attestations": [
                {"node_id": str(r["node_id"]), "node_title": r["node_title"], "level": r["level"], "issued_at": r["issued_at"].isoformat()}
                for r in rows
            ]}

    async def list_recent_evidence(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args["person_id"]
        node_ids = args.get("node_ids")
        since_days = args.get("since_days", 30)

        async with pool.acquire() as conn:
            conditions = [
                "e.person_id = $1",
                "e.observed_at >= now() - ($2 || ' days')::interval",
            ]
            params: list[Any] = [uuid.UUID(person_id), str(since_days)]
            idx = 3

            if node_ids:
                node_uuids = [uuid.UUID(n) for n in node_ids]
                conditions.append(f"e.node_id = ANY(${idx}::uuid[])")
                params.append(node_uuids)
                idx += 1

            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"""SELECT e.id, e.node_id, e.kind, e.score, e.confidence, e.source, e.observed_at
                    FROM evidence e
                    WHERE {where}
                    ORDER BY e.observed_at DESC
                    LIMIT 100""",
                *params,
            )
            return {
                "evidence": [
                    {
                        "id": str(r["id"]),
                        "node_id": str(r["node_id"]),
                        "kind": r["kind"],
                        "score": r["score"],
                        "confidence": r["confidence"],
                        "source": r["source"],
                        "observed_at": r["observed_at"].isoformat(),
                    }
                    for r in rows
                ]
            }

    return [
        ToolDef(
            name="assessments.create_question",
            description="Create a new question in a question bank",
            input_schema={
                "type": "object",
                "properties": {
                    "bank_id": {"type": "string"},
                    "type": {"type": "string"},
                    "stem": {"type": "string"},
                    "options": {"type": "object"},
                    "answer_key": {"type": "object"},
                    "bloom_level": {"type": "string"},
                    "difficulty": {"type": "string"},
                    "aligned_nodes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["bank_id", "type", "stem", "answer_key"],
            },
            handler=create_question,
            mutates=True,
            requires_approval=True,
        ),
        ToolDef(
            name="assessments.search_bank",
            description="Search questions in a question bank",
            input_schema={
                "type": "object",
                "properties": {
                    "bank_id": {"type": "string"},
                    "query": {"type": "string"},
                    "aligned_nodes": {"type": "array", "items": {"type": "string"}},
                },
            },
            handler=search_bank,
        ),
        ToolDef(
            name="assessments.get_submission",
            description="Get a submission by ID",
            input_schema={
                "type": "object",
                "properties": {
                    "submission_id": {"type": "string"},
                },
                "required": ["submission_id"],
            },
            handler=get_submission,
        ),
        ToolDef(
            name="assessments.get_rubric",
            description="Get a rubric by ID",
            input_schema={
                "type": "object",
                "properties": {
                    "rubric_id": {"type": "string"},
                },
                "required": ["rubric_id"],
            },
            handler=get_rubric,
        ),
        ToolDef(
            name="assessments.draft_grade",
            description="Create a draft grade for a submission",
            input_schema={
                "type": "object",
                "properties": {
                    "submission_id": {"type": "string"},
                    "rubric_id": {"type": "string"},
                    "scores": {"type": "object"},
                    "feedback": {"type": "object"},
                    "holistic_md": {"type": "string"},
                    "graded_by": {"type": "string"},
                },
                "required": ["submission_id", "scores", "feedback", "graded_by"],
            },
            handler=draft_grade,
            mutates=True,
        ),
        ToolDef(
            name="assessments.commit_grade",
            description="Commit a draft grade (makes it final)",
            input_schema={
                "type": "object",
                "properties": {
                    "grade_id": {"type": "string"},
                },
                "required": ["grade_id"],
            },
            handler=commit_grade,
            mutates=True,
            requires_approval=True,
        ),
        ToolDef(
            name="assessments.list_recent_evidence",
            description="List recent evidence for a person",
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "node_ids": {"type": "array", "items": {"type": "string"}},
                    "since_days": {"type": "integer"},
                },
                "required": ["person_id"],
            },
            handler=list_recent_evidence,
        ),
        ToolDef(
            name="attestations.attest",
            description="Create or update a mastery attestation for a student on a concept",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "node_id": {"type": "string"},
                "level": {"type": "string", "enum": ["emerging", "proficient", "mastery"]},
                "issuer_id": {"type": "string"},
            }, "required": ["person_id", "node_id", "level"]},
            handler=attest, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="attestations.get_student_attestations",
            description="Get all mastery attestations for a student, optionally filtered by course",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"},
            }, "required": ["person_id"]},
            handler=get_student_attestations, mutates=False,
        ),
    ]
