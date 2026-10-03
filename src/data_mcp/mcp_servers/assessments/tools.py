"""Assessments MCP server tool handlers."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from common import clock
from data_mcp.mcp_base import ToolDef
from data_mcp.mcp_servers._args import conflict, is_int, not_found, text_arg, uuid_arg
from data_mcp.mcp_servers._helpers import (
    parse_json_column,
    resolve_concept_id,
    validation_error,
)
from data_mcp.mcp_servers.assessments.access import load_viewer
from data_mcp.mcp_servers.assessments.formative import (
    formative_handlers,
    link_revision,
    submission_criteria,
)

MAX_CLOSING_CHARS = 20_000
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_criterion_key(key: str) -> str:
    """'Writing Mechanics', 'writing_mechanics' and 'writing-mechanics' are one criterion."""
    return _NON_WORD.sub("_", key.lower()).strip("_")


def _allowed_score(levels: Any, score: int) -> bool:
    """Level scores for §7.2 criteria; backfilled v1 criteria (levels carry `points`) take any
    whole number from 0 to the top level's points, as v1 grades did."""
    levels = parse_json_column(levels) if levels else []
    if not isinstance(levels, list) or not levels:
        return True
    points = [lv["points"] for lv in levels if isinstance(lv, dict)
              and isinstance(lv.get("points"), (int, float))]
    if points:
        return 0 <= score <= max(points)
    return score in {lv.get("score") for lv in levels if isinstance(lv, dict)}


def _final_scores(
    final_scores: dict[str, Any], criteria: list[Any], draft: Any,
) -> tuple[dict[str, int], list[tuple[uuid.UUID, int]]]:
    """(grades.scores, [(criterion_id, final_score)]); raises ValueError unless every rubric
    criterion has an allowed whole-number score. Keys outside the rubric must be draft keys."""
    by_norm = {normalize_criterion_key(c["key"]): c for c in criteria}
    draft_keys = {normalize_criterion_key(k): k for k in draft if isinstance(k, str)} \
        if isinstance(draft, dict) else {}
    scores: dict[str, int] = {}
    per_criterion: list[tuple[uuid.UUID, int]] = []
    for key, value in final_scores.items():
        norm = normalize_criterion_key(key) if isinstance(key, str) else ""
        if not is_int(value) or value < 0:
            raise ValueError(f"final score for {key} must be a non-negative whole number")
        crit = by_norm.get(norm)
        if crit is not None:
            if not _allowed_score(crit["levels"], value):
                raise ValueError(f"final score {value} is not a level of {crit['key']}")
            scores[crit["key"]] = value
            per_criterion.append((crit["id"], value))
        elif norm in draft_keys:
            scores[draft_keys[norm]] = value
        else:
            raise ValueError(f"{key} is not a criterion of this grade")
    required = list(by_norm) or list(draft_keys)
    missing = [k for k in required
               if k not in {normalize_criterion_key(s) for s in scores}]
    if missing:
        raise ValueError("final_scores is missing " + ", ".join(missing))
    return scores, per_criterion


HISTORY_DEFAULT_LIMIT = 20
HISTORY_MAX_LIMIT = 100


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all assessments server tool definitions."""
    formative = formative_handlers(pool)

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
            aligned_uuids = [uuid.UUID(n) for n in aligned_nodes] if aligned_nodes else []
            await conn.execute(
                """INSERT INTO questions
                   (id, bank_id, type, stem, options, answer_key, bloom_level, difficulty, aligned_nodes)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                question_id,
                uuid.UUID(bank_id),
                q_type,
                stem,
                json.dumps(options) if options is not None else None,
                json.dumps(answer_key),
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
            rows = await conn.fetch(
                """SELECT q.id, q.type, q.stem, q.options, q.bloom_level, q.difficulty, q.aligned_nodes
                   FROM questions q
                   JOIN question_banks b ON b.id = q.bank_id
                   WHERE ($1::uuid IS NULL OR q.bank_id = $1)
                     AND COALESCE(b.metadata->>'kind', '') <> 'practice'
                     AND ($2::text IS NULL OR q.stem ILIKE $2)
                     AND ($3::uuid[] IS NULL OR q.aligned_nodes && $3)
                   LIMIT 50""",
                uuid.UUID(bank_id) if bank_id else None,
                f"%{query}%" if query else None,
                [uuid.UUID(n) for n in aligned_nodes] if aligned_nodes else None,
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
        rubric_id = args["rubric_id"]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, title, criteria FROM rubrics WHERE id = $1",
                uuid.UUID(rubric_id),
            )
            if not row:
                return {"error": "Rubric not found"}
            return {
                "id": str(row["id"]),
                "title": row["title"],
                "criteria": parse_json_column(row["criteria"]),
            }

    async def draft_grade(args: dict[str, Any]) -> dict[str, Any]:
        submission_id = args["submission_id"]
        rubric_id = args.get("rubric_id")
        scores = args["scores"]
        feedback = args["feedback"]
        holistic_md = args.get("holistic_md")
        graded_by = args["graded_by"]

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
                json.dumps(scores),
                json.dumps(feedback),
                holistic_md,
                uuid.UUID(graded_by),
            )
            await _record_ai_scores(conn, uuid.UUID(submission_id), rubric_id, scores, feedback)
            return {"grade_id": str(grade_id)}

    async def _grade_criteria(conn: asyncpg.Connection, submission_id: uuid.UUID,
                              rubric_id: str | uuid.UUID | None) -> list[asyncpg.Record]:
        """rubric_criteria of the grade's rubric, else of the submission's assignment."""
        return await conn.fetch(
            """SELECT rc.id, rc.key, rc.levels FROM rubric_criteria rc
               WHERE rc.rubric_id::text = COALESCE($2::text, (
                 SELECT a.metadata->>'rubric_id' FROM submissions s
                 JOIN nodes a ON a.id = s.assignment_node WHERE s.id = $1))
               ORDER BY rc.key""",
            submission_id, str(rubric_id) if rubric_id else None,
        )

    async def _record_ai_scores(conn: asyncpg.Connection, submission_id: uuid.UUID,
                                rubric_id: str | None, scores: Any, feedback: Any) -> None:
        """A final version's draft scores become criterion_scores.ai_score; drafts keep the
        feedback agent's scores, which a learner may already have been shown."""
        status = await conn.fetchval("SELECT status FROM submissions WHERE id = $1",
                                     submission_id)
        if status != "final" or not isinstance(scores, dict):
            return
        by_key = {normalize_criterion_key(k): v for k, v in scores.items() if isinstance(k, str)}
        notes = ({normalize_criterion_key(k): v for k, v in feedback.items()
                  if isinstance(k, str) and isinstance(v, str)}
                 if isinstance(feedback, dict) else {})
        rows = [
            (submission_id, c["id"], by_key[c["key"]], notes.get(c["key"]))
            for c in await _grade_criteria(conn, submission_id, rubric_id)
            if is_int(by_key.get(c["key"]))
        ]
        await conn.executemany(
            """INSERT INTO criterion_scores (submission_id, criterion_id, ai_score, ai_rationale)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (submission_id, criterion_id) DO UPDATE SET
                 ai_score = EXCLUDED.ai_score,
                 ai_rationale = COALESCE(EXCLUDED.ai_rationale, criterion_scores.ai_rationale)""",
            rows,
        )

    async def commit_grade(args: dict[str, Any]) -> dict[str, Any]:
        try:
            grade_id = uuid_arg(args, "grade_id", required=True)
            final_scores = args.get("final_scores")
            if not isinstance(final_scores, dict) or not final_scores:
                raise ValueError("final_scores must map each rubric criterion to a score")
            holistic_md = text_arg(args.get("holistic_md"), "holistic_md",
                                   max_chars=MAX_CLOSING_CHARS)
            edits = args.get("feedback")
            if edits is not None and not (isinstance(edits, dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in edits.items())):
                raise ValueError("feedback must map criterion keys to text")
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT id, submission_id, rubric_id, scores, feedback, is_draft
                   FROM grades WHERE id = $1 FOR UPDATE""",
                grade_id,
            )
            if not row:
                return not_found("Grade not found")
            if not row["is_draft"]:
                return conflict("Grade is already committed")
            criteria = await _grade_criteria(conn, row["submission_id"], row["rubric_id"])
            draft = parse_json_column(row["scores"]) or {}
            try:
                scores, per_criterion = _final_scores(final_scores, criteria, draft)
            except ValueError as exc:
                return validation_error(str(exc))
            merged = parse_json_column(row["feedback"]) or {}
            if not isinstance(merged, dict):
                merged = {}
            merged.update(edits or {})
            await conn.executemany(
                """INSERT INTO criterion_scores (submission_id, criterion_id, final_score)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (submission_id, criterion_id) DO UPDATE SET
                     final_score = EXCLUDED.final_score""",
                [(row["submission_id"], cid, score) for cid, score in per_criterion],
            )
            committed_at = await conn.fetchval(
                """UPDATE grades SET is_draft = false, committed_at = now(), scores = $2,
                          holistic_md = $3, feedback = $4
                   WHERE id = $1 RETURNING committed_at""",
                grade_id, json.dumps(scores), holistic_md, json.dumps(merged),
            )
            await link_revision(conn, row["submission_id"], dict(per_criterion))
            return {
                "committed": True,
                "committed_at": committed_at.isoformat(),
            }

    async def attest(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        node_id = args.get("node_id")
        level = args.get("level")
        issuer_id = args.get("issuer_id")
        session_id = args.get("session_id")
        if not person_id or not node_id or not level:
            return {"error": "person_id, node_id, and level are required"}
        if level not in ("emerging", "proficient", "mastery"):
            return {"error": "level must be emerging, proficient, or mastery"}
        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id)
            nid = await resolve_concept_id(conn, node_id)
            if nid is None:
                return {"error": f"Concept not found: {node_id}"}
            iid = uuid.UUID(issuer_id) if issuer_id else None
            sid = uuid.UUID(session_id) if session_id else None

            # Enforce mastery timing: mastery requires a prior attestation from a different session
            original_level = level
            if level == "mastery" and sid:
                prior = await conn.fetchrow(
                    """SELECT session_id FROM attestations
                       WHERE person_id = $1 AND node_id = $2 AND session_id IS NOT NULL AND session_id != $3
                       LIMIT 1""",
                    pid, nid, sid,
                )
                if not prior:
                    level = "proficient"

            existing = await conn.fetchrow(
                "SELECT id, level FROM attestations WHERE person_id = $1 AND node_id = $2", pid, nid)
            if existing:
                await conn.execute(
                    "UPDATE attestations SET level = $1, issuer_id = $2, issued_at = now(), session_id = $3 WHERE id = $4",
                    level, iid, sid, existing["id"])
                result = {"attestation_id": str(existing["id"]), "updated": True, "previous_level": existing["level"], "level": level}
            else:
                att_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO attestations (id, person_id, node_id, level, issuer_id, session_id) VALUES ($1, $2, $3, $4, $5, $6)",
                    att_id, pid, nid, level, iid, sid)
                result = {"attestation_id": str(att_id), "created": True, "level": level}

            if original_level == "mastery" and level == "proficient":
                result["downgraded"] = True
                result["reason"] = "Cannot attest mastery in the same session as initial teaching. Auto-downgraded to proficient."

            # Auto-check for credential readiness when mastery is achieved
            if level == "mastery":
                # Find the course this concept belongs to
                course_row = await conn.fetchrow(
                    """SELECT e2.to_node as course_id FROM edges e
                       JOIN nodes mod ON mod.id = e.to_node AND mod.kind = 'module'
                       JOIN edges e2 ON e2.from_node = mod.id AND e2.kind = 'part_of'
                       JOIN nodes course ON course.id = e2.to_node AND course.kind = 'course'
                       WHERE e.from_node = $1 AND e.kind = 'part_of'
                       LIMIT 1""",
                    nid,
                )
                if course_row:
                    check_result = await check_and_create_pending({
                        "person_id": person_id,
                        "course_id": str(course_row["course_id"]),
                    })
                    if check_result.get("created"):
                        result["credentials_pending"] = check_result["created"]

            return result

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
        """Private evidence (practice, drafts) is returned only when requester_id is the
        learner; any other or absent requester gets course/program evidence only."""
        try:
            person = uuid_arg(args, "person_id", required=True)
            requester_id = uuid_arg(args, "requester_id", required=False)
        except ValueError as exc:
            return {**validation_error(str(exc)), "evidence": []}
        include_private = requester_id is not None and requester_id == person
        node_ids = args.get("node_ids")
        since_days = args.get("since_days", 30)
        if isinstance(since_days, str) and since_days.strip().isdigit():
            since_days = int(since_days)
        if isinstance(since_days, bool) or not isinstance(since_days, int) or since_days < 0:
            return {
                **validation_error(
                    f"Invalid since_days {since_days!r}; expected a non-negative integer"
                ),
                "evidence": [],
            }

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT e.id, e.node_id, e.kind, e.score, e.confidence, e.source, e.observed_at,
                          e.visibility::text AS visibility
                   FROM evidence e
                   WHERE e.person_id = $1
                     AND e.observed_at >= $4::timestamptz - make_interval(days => $2)
                     AND e.observed_at <= $4::timestamptz
                     AND ($3::uuid[] IS NULL OR e.node_id = ANY($3))
                     AND ($5::bool OR e.visibility::text <> 'private')
                   ORDER BY e.observed_at DESC, e.kind, e.score, e.source,
                            e.node_id, e.payload::text, e.id
                   LIMIT 100""",
                person,
                since_days,
                [uuid.UUID(n) for n in node_ids] if node_ids else None,
                clock.now(),
                include_private,
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
                        "visibility": r["visibility"],
                    }
                    for r in rows
                ]
            }

    async def list_submission_history(args: dict[str, Any]) -> dict[str, Any]:
        """Newest first. Without person_id it lists every learner's submissions in the scope.
        Criteria are the assignment's rubric criteria (node metadata rubric_id) plus any
        criterion scored on the submission. Unless requester_id is faculty of the submission's
        course (or an admin), unreleased feedback and uncommitted final scores are null."""
        try:
            person = args.get("person_id")
            assignment = args.get("assignment_node")
            course = args.get("course_id")
            requester = args.get("requester_id")
            person_id = uuid.UUID(str(person)) if person else None
            assignment_id = uuid.UUID(str(assignment)) if assignment else None
            course_id = uuid.UUID(str(course)) if course else None
            requester_id = uuid.UUID(str(requester)) if requester else None
        except ValueError:
            return {**validation_error(
                "person_id, assignment_node, course_id and requester_id must be UUIDs"),
                "submissions": []}
        if assignment_id is None and course_id is None:
            return {**validation_error(
                "One of assignment_node or course_id is required"), "submissions": []}
        title = args.get("assignment_title")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            return {**validation_error(
                "assignment_title must be a non-empty string"), "submissions": []}
        limit = args.get("limit", HISTORY_DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= HISTORY_MAX_LIMIT:
            return {**validation_error(
                f"Invalid limit {limit!r}; expected an integer from 1 to {HISTORY_MAX_LIMIT}"),
                "submissions": []}

        async with pool.acquire() as conn:
            subs = await conn.fetch(
                """SELECT s.id, s.person_id, s.assignment_node, s.version, s.status,
                          s.parent_id, s.submitted_at,
                          COALESCE(s.course_node::text, a.metadata->>'course_id') AS course,
                          a.title AS assignment_title, a.metadata->>'rubric_id' AS rubric_id
                   FROM submissions s
                   JOIN nodes a ON a.id = s.assignment_node
                   WHERE ($1::uuid IS NULL OR s.person_id = $1)
                     AND ($2::uuid IS NULL OR s.assignment_node = $2)
                     AND ($3::uuid IS NULL OR s.course_node = $3
                          OR (s.course_node IS NULL AND a.metadata->>'course_id' = $3::text))
                     AND ($5::text IS NULL OR strpos(lower(a.title), lower($5)) > 0)
                   ORDER BY s.submitted_at DESC, s.version DESC, s.id
                   LIMIT $4""",
                person_id, assignment_id, course_id, limit,
                title.strip() if title is not None else None,
            )
            viewer = await load_viewer(conn, requester_id)
            criteria, statuses = await submission_criteria(conn, subs, viewer)
        return {"submissions": [
            {
                "id": str(r["id"]),
                "person_id": str(r["person_id"]),
                "assignment_node": str(r["assignment_node"]),
                "assignment_title": r["assignment_title"],
                "course_id": r["course"],
                "rubric_id": r["rubric_id"],
                "version": r["version"],
                "status": r["status"],
                "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
                "submitted_at": r["submitted_at"].isoformat(),
                "feedback_status": statuses[r["id"]],
                "criteria": criteria.get(r["id"], []),
            }
            for r in subs
        ]}

    # ── Credential management ──

    async def check_and_create_pending(args: dict[str, Any]) -> dict[str, Any]:
        """Check if a student has mastered all concepts in any microcredential and create pending credentials."""
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        if not person_id or not course_id:
            return {"error": "person_id and course_id are required"}

        async with pool.acquire() as conn:
            # Get microcredentials for this course: course -> module -> microcredential
            mc_rows = await conn.fetch(
                """SELECT DISTINCT n.id, n.title
                   FROM nodes n
                   WHERE n.kind = 'microcredential'
                   AND EXISTS (
                       SELECT 1 FROM edges e
                       JOIN nodes mod ON mod.id = e.from_node AND mod.kind = 'module'
                       JOIN edges e2 ON e2.from_node = mod.id AND e2.to_node = $1 AND e2.kind = 'part_of'
                       WHERE e.to_node = n.id AND e.kind = 'contributes_to'
                   )""",
                uuid.UUID(course_id),
            )

            created = []
            for mc in mc_rows:
                mc_id = mc["id"]

                # Skip if already pending or issued
                existing = await conn.fetchval(
                    "SELECT id FROM pending_credentials WHERE person_id = $1 AND microcredential_id = $2",
                    uuid.UUID(person_id), mc_id,
                )
                if existing:
                    continue
                issued = await conn.fetchval(
                    "SELECT id FROM issued_credentials WHERE person_id = $1 AND microcredential_id = $2",
                    uuid.UUID(person_id), mc_id,
                )
                if issued:
                    continue

                # Get all concepts in this microcredential: concept -part_of-> module -contributes_to-> mc
                concept_ids = await conn.fetch(
                    """SELECT DISTINCT c.id FROM nodes c
                       JOIN edges e ON e.from_node = c.id AND e.kind = 'part_of'
                       JOIN nodes mod ON mod.id = e.to_node AND mod.kind = 'module'
                       JOIN edges e2 ON e2.from_node = mod.id AND e2.to_node = $1 AND e2.kind = 'contributes_to'
                       WHERE c.kind = 'concept'""",
                    mc_id,
                )

                if not concept_ids:
                    continue

                # Check if all concepts have mastery attestation
                all_mastered = True
                for row in concept_ids:
                    att = await conn.fetchval(
                        """SELECT level FROM attestations
                           WHERE person_id = $1 AND node_id = $2
                           ORDER BY issued_at DESC LIMIT 1""",
                        uuid.UUID(person_id), row["id"],
                    )
                    if att != "mastery":
                        all_mastered = False
                        break

                if all_mastered:
                    await conn.execute(
                        """INSERT INTO pending_credentials (person_id, microcredential_id, course_id)
                           VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                        uuid.UUID(person_id), mc_id, uuid.UUID(course_id),
                    )
                    created.append({"microcredential_id": str(mc_id), "title": mc["title"]})

            return {"created": created}

    async def list_pending_credentials(args: dict[str, Any]) -> dict[str, Any]:
        """List pending credentials for a course, optionally filtered by student."""
        course_id = args.get("course_id")
        person_id = args.get("person_id")
        if not course_id:
            return {"error": "course_id is required"}

        async with pool.acquire() as conn:
            if person_id:
                rows = await conn.fetch(
                    """SELECT pc.id, pc.person_id, pc.microcredential_id, pc.created_at, pc.status,
                              p.display_name as student_name, n.title as credential_title
                       FROM pending_credentials pc
                       JOIN persons p ON p.id = pc.person_id
                       JOIN nodes n ON n.id = pc.microcredential_id
                       WHERE pc.course_id = $1 AND pc.person_id = $2 AND pc.status = 'pending'
                       ORDER BY pc.created_at DESC""",
                    uuid.UUID(course_id), uuid.UUID(person_id),
                )
            else:
                rows = await conn.fetch(
                    """SELECT pc.id, pc.person_id, pc.microcredential_id, pc.created_at, pc.status,
                              p.display_name as student_name, n.title as credential_title
                       FROM pending_credentials pc
                       JOIN persons p ON p.id = pc.person_id
                       JOIN nodes n ON n.id = pc.microcredential_id
                       WHERE pc.course_id = $1 AND pc.status = 'pending'
                       ORDER BY pc.created_at DESC""",
                    uuid.UUID(course_id),
                )

            return {
                "pending": [
                    {
                        "id": str(r["id"]),
                        "person_id": str(r["person_id"]),
                        "student_name": r["student_name"],
                        "microcredential_id": str(r["microcredential_id"]),
                        "credential_title": r["credential_title"],
                        "created_at": r["created_at"].isoformat(),
                    }
                    for r in rows
                ]
            }

    async def get_credential_evidence(args: dict[str, Any]) -> dict[str, Any]:
        """Get evidence supporting a pending credential — attestations and session data."""
        pending_id = args.get("pending_id")
        if not pending_id:
            return {"error": "pending_id is required"}

        async with pool.acquire() as conn:
            pc = await conn.fetchrow(
                """SELECT pc.*, p.display_name as student_name, n.title as credential_title
                   FROM pending_credentials pc
                   JOIN persons p ON p.id = pc.person_id
                   JOIN nodes n ON n.id = pc.microcredential_id
                   WHERE pc.id = $1""",
                uuid.UUID(pending_id),
            )
            if not pc:
                return {"error": "Pending credential not found"}

            # Get all concepts in this microcredential with their attestations
            concepts = await conn.fetch(
                """SELECT c.id, c.title,
                          (SELECT a.level FROM attestations a WHERE a.person_id = $1 AND a.node_id = c.id ORDER BY a.issued_at DESC LIMIT 1) as level,
                          (SELECT a.issued_at FROM attestations a WHERE a.person_id = $1 AND a.node_id = c.id ORDER BY a.issued_at DESC LIMIT 1) as attested_at
                   FROM nodes c
                   JOIN edges e ON e.from_node = c.id AND e.kind = 'part_of'
                   JOIN nodes mod ON mod.id = e.to_node AND mod.kind = 'module'
                   JOIN edges e2 ON e2.from_node = mod.id AND e2.to_node = $2 AND e2.kind = 'contributes_to'
                   WHERE c.kind = 'concept'
                   ORDER BY c.title""",
                pc["person_id"], pc["microcredential_id"],
            )

            # Get session count for this student in this course
            session_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE person_id = $1 AND course_node = $2 AND persona = 'student'",
                pc["person_id"], pc["course_id"],
            )

            return {
                "pending_id": str(pc["id"]),
                "student_name": pc["student_name"],
                "credential_title": pc["credential_title"],
                "created_at": pc["created_at"].isoformat(),
                "session_count": session_count,
                "concepts": [
                    {
                        "id": str(c["id"]),
                        "title": c["title"],
                        "level": c["level"],
                        "attested_at": c["attested_at"].isoformat() if c["attested_at"] else None,
                    }
                    for c in concepts
                ],
            }

    async def approve_credential(args: dict[str, Any]) -> dict[str, Any]:
        """Approve a pending credential and generate OB3 JSON-LD."""
        pending_id = args.get("pending_id")
        reviewer_id = args.get("reviewer_id")
        if not pending_id or not reviewer_id:
            return {"error": "pending_id and reviewer_id are required"}

        async with pool.acquire() as conn:
            pc = await conn.fetchrow(
                """SELECT pc.*, p.display_name as student_name, p.email as student_email,
                          n.title as credential_title, n.description as credential_description
                   FROM pending_credentials pc
                   JOIN persons p ON p.id = pc.person_id
                   JOIN nodes n ON n.id = pc.microcredential_id
                   WHERE pc.id = $1 AND pc.status = 'pending'""",
                uuid.UUID(pending_id),
            )
            if not pc:
                return {"error": "Pending credential not found or already processed"}

            # Get course title
            course = await conn.fetchrow("SELECT title FROM nodes WHERE id = $1", pc["course_id"])
            course_title = course["title"] if course else "Unknown Course"

            # Get reviewer info
            reviewer = await conn.fetchrow("SELECT display_name FROM persons WHERE id = $1", uuid.UUID(reviewer_id))

            # Generate OB3 JSON-LD credential
            credential_id = str(uuid.uuid4())
            ob3_credential = {
                "@context": [
                    "https://www.w3.org/ns/credentials/v2",
                    "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json",
                ],
                "id": f"urn:uuid:{credential_id}",
                "type": ["VerifiableCredential", "OpenBadgeCredential"],
                "issuer": {
                    "id": "urn:uuid:ai-first-lms",
                    "type": ["Profile"],
                    "name": "AI-First LMS",
                },
                "validFrom": datetime.now(timezone.utc).isoformat(),
                "credentialSubject": {
                    "id": f"urn:uuid:{pc['person_id']}",
                    "type": ["AchievementSubject"],
                    "name": pc["student_name"],
                    "achievement": {
                        "id": f"urn:uuid:{pc['microcredential_id']}",
                        "type": ["Achievement"],
                        "name": pc["credential_title"],
                        "description": pc["credential_description"] or f"Mastery of {pc['credential_title']} in {course_title}",
                        "criteria": {
                            "narrative": f"Demonstrated mastery of all concepts in the {pc['credential_title']} microcredential through AI-assisted adaptive learning in {course_title}."
                        },
                    },
                },
                "evidence": [
                    {
                        "id": f"urn:uuid:{pc['id']}",
                        "type": ["Evidence"],
                        "name": "AI Tutor Assessment",
                        "description": f"Mastery verified through adaptive tutoring sessions. Approved by {reviewer['display_name'] if reviewer else 'instructor'}.",
                    }
                ],
            }

            # Mark pending as approved
            await conn.execute(
                "UPDATE pending_credentials SET status = 'approved', reviewed_by = $1, reviewed_at = now() WHERE id = $2",
                uuid.UUID(reviewer_id), uuid.UUID(pending_id),
            )

            # Insert issued credential
            await conn.execute(
                """INSERT INTO issued_credentials (person_id, microcredential_id, course_id, issued_by, credential_json)
                   VALUES ($1, $2, $3, $4, $5) ON CONFLICT (person_id, microcredential_id) DO NOTHING""",
                pc["person_id"], pc["microcredential_id"], pc["course_id"],
                uuid.UUID(reviewer_id), json.dumps(ob3_credential),
            )

            return {"approved": True, "credential_id": credential_id}

    async def reject_credential(args: dict[str, Any]) -> dict[str, Any]:
        """Close a pending credential without issuing it. The caller records the reason."""
        try:
            pending_id = uuid_arg(args, "pending_id", required=True)
            reviewer_id = uuid_arg(args, "reviewer_id", required=True)
            if args.get("reason") is not None:
                text_arg(args["reason"], "reason")
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn:
            status = await conn.fetchval(
                """UPDATE pending_credentials SET status = 'rejected', reviewed_by = $2,
                          reviewed_at = now()
                   WHERE id = $1 AND status = 'pending'
                   RETURNING status""",
                pending_id, reviewer_id,
            )
            if status is None:
                exists = await conn.fetchval(
                    "SELECT 1 FROM pending_credentials WHERE id = $1", pending_id)
                if exists is None:
                    return not_found("Pending credential not found")
                return conflict("This credential was already reviewed")
        return {"rejected": True, "pending_id": str(pending_id)}

    async def list_issued_credentials(args: dict[str, Any]) -> dict[str, Any]:
        """List issued credentials for a student."""
        person_id = args.get("person_id")
        if not person_id:
            return {"error": "person_id is required"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT ic.id, ic.microcredential_id, ic.course_id, ic.issued_at,
                          n.title as credential_title, nc.title as course_title,
                          p.display_name as issued_by_name
                   FROM issued_credentials ic
                   JOIN nodes n ON n.id = ic.microcredential_id
                   LEFT JOIN nodes nc ON nc.id = ic.course_id
                   JOIN persons p ON p.id = ic.issued_by
                   WHERE ic.person_id = $1
                   ORDER BY ic.issued_at DESC""",
                uuid.UUID(person_id),
            )
            return {
                "credentials": [
                    {
                        "id": str(r["id"]),
                        "credential_title": r["credential_title"],
                        "course_title": r["course_title"] or "Unknown",
                        "issued_at": r["issued_at"].isoformat(),
                        "issued_by": r["issued_by_name"],
                    }
                    for r in rows
                ]
            }

    # ── System settings ──

    async def get_settings(args: dict[str, Any]) -> dict[str, Any]:
        key = args.get("key")
        async with pool.acquire() as conn:
            if key:
                row = await conn.fetchrow("SELECT value FROM system_settings WHERE key = $1", key)
                return {"key": key, "value": row["value"] if row else None}
            else:
                rows = await conn.fetch("SELECT key, value FROM system_settings ORDER BY key")
                return {"settings": {r["key"]: r["value"] for r in rows}}

    async def save_settings(args: dict[str, Any]) -> dict[str, Any]:
        key = args.get("key")
        value = args.get("value")
        if not key or value is None:
            return {"error": "key and value are required"}
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, now())
                   ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()""",
                key, json.dumps(value),
            )
            return {"saved": True}

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
                    "final_scores": {"type": "object"},
                    "holistic_md": {"type": "string"},
                    "feedback": {"type": "object"},
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
                    "requester_id": {"type": "string"},
                },
                "required": ["person_id"],
            },
            handler=list_recent_evidence,
        ),
        ToolDef(
            name="assessments.list_submission_history",
            description=(
                "List submissions (all versions, newest first) for an assignment or a course, "
                "for one learner or all learners, with per-criterion rubric scores"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "assignment_node": {"type": "string"},
                    "assignment_title": {"type": "string"},
                    "course_id": {"type": "string"},
                    "limit": {"type": "integer"},
                    "requester_id": {"type": "string"},
                },
            },
            handler=list_submission_history,
        ),
        ToolDef(
            name="attestations.attest",
            description="Create or update a mastery attestation for a student on a concept",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "node_id": {"type": "string"},
                "level": {"type": "string", "enum": ["emerging", "proficient", "mastery"]},
                "issuer_id": {"type": "string"},
                "session_id": {"type": "string", "description": "Session UUID. When level=mastery, a prior attestation from a different session is required or the level is auto-downgraded to proficient."},
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
        ToolDef(
            name="assessments.check_pending_credentials",
            description="Check if a student has mastered all concepts in any microcredential and create pending credentials",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"},
            }, "required": ["person_id", "course_id"]},
            handler=check_and_create_pending, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="assessments.list_pending_credentials",
            description="List pending credentials for a course awaiting instructor approval",
            input_schema={"type": "object", "properties": {
                "course_id": {"type": "string"}, "person_id": {"type": "string"},
            }, "required": ["course_id"]},
            handler=list_pending_credentials, mutates=False,
        ),
        ToolDef(
            name="assessments.get_credential_evidence",
            description="Get mastery evidence supporting a pending credential",
            input_schema={"type": "object", "properties": {
                "pending_id": {"type": "string"},
            }, "required": ["pending_id"]},
            handler=get_credential_evidence, mutates=False,
        ),
        ToolDef(
            name="assessments.approve_credential",
            description="Approve a pending credential and generate OB3 badge",
            input_schema={"type": "object", "properties": {
                "pending_id": {"type": "string"}, "reviewer_id": {"type": "string"},
            }, "required": ["pending_id", "reviewer_id"]},
            handler=approve_credential, mutates=True, requires_approval=True,
        ),
        ToolDef(
            name="assessments.reject_credential",
            description="Reject a pending credential so it is never issued",
            input_schema={"type": "object", "properties": {
                "pending_id": {"type": "string"}, "reviewer_id": {"type": "string"},
                "reason": {"type": "string"},
            }, "required": ["pending_id", "reviewer_id"]},
            handler=reject_credential, mutates=True, requires_approval=True,
        ),
        ToolDef(
            name="assessments.list_issued_credentials",
            description="List issued OB3 badge credentials for a student",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"},
            }, "required": ["person_id"]},
            handler=list_issued_credentials, mutates=False,
        ),
        ToolDef(
            name="assessments.get_settings",
            description="Get system settings (badge provider config, etc.)",
            input_schema={"type": "object", "properties": {
                "key": {"type": "string"},
            }},
            handler=get_settings, mutates=False,
        ),
        ToolDef(
            name="assessments.save_settings",
            description="Save a system setting",
            input_schema={"type": "object", "properties": {
                "key": {"type": "string"}, "value": {},
            }, "required": ["key", "value"]},
            handler=save_settings, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="assessments.submit",
            description=(
                "Submit a draft, revision or final version of an assignment for the student "
                "themself; a revision names the latest version as parent_id"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "assignment_node": {"type": "string"},
                    "body_md": {"type": "string"},
                    "attachments": {"type": "array", "items": {"type": "object"}},
                    "status": {"type": "string", "enum": ["draft", "final"]},
                    "parent_id": {"type": "string"},
                },
                "required": ["person_id", "assignment_node", "body_md", "status"],
            },
            handler=formative["assessments.submit"],
            mutates=True,
        ),
        ToolDef(
            name="assessments.save_criterion_feedback",
            description=(
                "Save formative, criterion-level feedback (a rubric level, rationale, quoted "
                "evidence spans and one next step per criterion). Never grades and never "
                "releases feedback to the student"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "submission_id": {"type": "string"},
                    "criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "criterion_id": {"type": "string"},
                                "ai_score": {"type": "integer"},
                                "ai_rationale": {"type": "string"},
                                "ai_evidence_spans": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "quote": {"type": "string"},
                                            "start": {"type": "integer"},
                                            "end": {"type": "integer"},
                                        },
                                        "required": ["quote"],
                                    },
                                },
                                "next_step": {"type": "string"},
                            },
                            "required": ["criterion_id", "ai_score", "ai_rationale",
                                         "ai_evidence_spans", "next_step"],
                        },
                    },
                    "requester_id": {"type": "string"},
                },
                "required": ["submission_id", "criteria"],
            },
            handler=formative["assessments.save_criterion_feedback"],
            mutates=True,
        ),
        ToolDef(
            name="assessments.release_feedback",
            description=(
                "Release (optionally edited) or suppress criterion feedback on a submission"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "submission_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["release", "suppress"]},
                    "criterion_ids": {"type": "array", "items": {"type": "string"}},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "criterion_id": {"type": "string"},
                                "ai_score": {"type": "integer"},
                                "ai_rationale": {"type": "string"},
                                "next_step": {"type": "string"},
                            },
                            "required": ["criterion_id"],
                        },
                    },
                    "reviewer_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["submission_id"],
            },
            handler=formative["assessments.release_feedback"],
            mutates=True,
            requires_approval=True,
        ),
        ToolDef(
            name="assessments.get_improvement",
            description=(
                "Student x criterion improvement trajectories for a course, with plateaued, "
                "regressed and ready_for_summative flags"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "student_id": {"type": "string"},
                    "criterion_id": {"type": "string"},
                    "requester_id": {"type": "string"},
                },
                "required": ["course_id", "requester_id"],
            },
            handler=formative["assessments.get_improvement"],
        ),
        ToolDef(
            name="assessments.weaknesses",
            description=(
                "Criteria a student is below target on in at least 2 of their last N scored "
                "submissions in a course (deterministic weakness detector)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string"},
                    "course_id": {"type": "string"},
                    "window": {"type": "integer"},
                },
                "required": ["student_id", "course_id"],
            },
            handler=formative["assessments.weaknesses"],
        ),
        ToolDef(
            name="assessments.propose_alignment",
            description=(
                "Context for aligning an assignment to course outcomes (syllabus, ranked "
                "candidate outcomes, existing criteria); with the agent's 3-6 drafted criteria "
                "it also returns them validated as a proposal with outcome links"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "assignment_node": {"type": "string"},
                    "max_outcomes": {"type": "integer"},
                    "criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "description": {"type": "string"},
                                "levels": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "score": {"type": "integer"},
                                            "label": {"type": "string"},
                                            "descriptor": {"type": "string"},
                                        },
                                        "required": ["score", "label", "descriptor"],
                                    },
                                },
                                "outcome_nodes": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["key", "description", "levels"],
                        },
                    },
                },
                "required": ["assignment_node"],
            },
            handler=formative["assessments.propose_alignment"],
        ),
        ToolDef(
            name="assessments.apply_alignment",
            description=(
                "Store the criteria faculty accepted or edited from an alignment proposal: "
                "upserts rubric_criteria (with outcome_nodes) on the assignment's rubric, "
                "creating the rubric if needed, and links the assignment to those outcomes"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "assignment_node": {"type": "string"},
                    "criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "description": {"type": "string"},
                                "levels": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "score": {"type": "integer"},
                                            "label": {"type": "string"},
                                            "descriptor": {"type": "string"},
                                        },
                                        "required": ["score", "label", "descriptor"],
                                    },
                                },
                                "outcome_nodes": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["key"],
                        },
                    },
                    "requester_id": {"type": "string"},
                },
                "required": ["assignment_node", "criteria", "requester_id"],
            },
            handler=formative["assessments.apply_alignment"],
            mutates=True,
            requires_approval=True,
        ),
        ToolDef(
            name="assessments.record_practice_attempt",
            description=(
                "Record a student's attempt at their own practice set as private evidence and "
                "return per-item correctness from the stored answer key"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "practice_set_id": {"type": "string"},
                    "answers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question_id": {"type": "string"},
                                "answer": {"type": "string"},
                            },
                            "required": ["question_id", "answer"],
                        },
                    },
                },
                "required": ["person_id", "practice_set_id", "answers"],
            },
            handler=formative["assessments.record_practice_attempt"],
            mutates=True,
        ),
        ToolDef(
            name="assessments.grading_status",
            description=(
                "Grading pipeline status per assignment: final submissions, draft grades "
                "awaiting commit, committed grades"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "assignment_id": {"type": "string"},
                },
            },
            handler=formative["assessments.grading_status"],
        ),
    ]
