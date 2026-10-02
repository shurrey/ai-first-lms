"""Roster MCP server tool handlers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef
from data_mcp.mcp_servers._helpers import parse_json_column, resolve_concept_id


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:

    async def get(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args["person_id"]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, display_name, roles, attributes FROM persons WHERE id = $1",
                uuid.UUID(person_id),
            )
            if not row:
                return {"error": "Person not found"}
            return {
                "id": str(row["id"]),
                "display_name": row["display_name"],
                "roles": row["roles"],
                "attributes": row["attributes"],
            }

    async def get_student(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args["person_id"]
        course_id = args.get("course_id")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, display_name, roles, attributes FROM persons WHERE id = $1",
                uuid.UUID(person_id),
            )
            if not row:
                return {"error": "Person not found"}

            result: dict[str, Any] = {
                "id": str(row["id"]),
                "display_name": row["display_name"],
                "roles": row["roles"],
                "attributes": row["attributes"],
            }

            if course_id:
                enrollment = await conn.fetchrow(
                    "SELECT role, status, enrolled_at FROM enrollments WHERE person_id = $1 AND course_node = $2",
                    uuid.UUID(person_id), uuid.UUID(course_id),
                )
                if enrollment:
                    result["enrollment"] = {
                        "role": enrollment["role"],
                        "status": enrollment["status"],
                        "enrolled_at": enrollment["enrolled_at"].isoformat(),
                    }

            return result

    async def get_student_context(args: dict[str, Any]) -> dict[str, Any]:
        person_id = uuid.UUID(args["person_id"])
        course_id = uuid.UUID(args["course_id"])
        async with pool.acquire() as conn:
            # Recent evidence
            ev_rows = await conn.fetch(
                """SELECT e.node_id, e.kind, e.score, e.observed_at, n.title
                   FROM evidence e
                   JOIN nodes n ON n.id = e.node_id
                   WHERE e.person_id = $1
                   ORDER BY e.observed_at DESC, n.title, e.kind, e.score LIMIT 10""",
                person_id,
            )
            recent_evidence = [
                {"node_id": str(r["node_id"]), "kind": r["kind"],
                 "score": r["score"], "title": r["title"],
                 "observed_at": r["observed_at"].isoformat()}
                for r in ev_rows
            ]

            # Current modules (enrolled course modules)
            mod_rows = await conn.fetch(
                """SELECT m.module_id, m.title
                   FROM modules m WHERE m.course_id = $1
                   ORDER BY (m.metadata->>'order')::int, m.title""",
                course_id,
            )
            current_modules = [
                {"id": str(r["module_id"]), "title": r["title"]}
                for r in mod_rows
            ]

            # Upcoming assignments
            assign_rows = await conn.fetch(
                """SELECT a.assignment_id, a.title, a.due_at
                   FROM assignments a
                   WHERE a.course_id = $1 AND a.due_at > now()
                   ORDER BY a.due_at, a.title LIMIT 5""",
                course_id,
            )
            upcoming = [
                {"id": str(r["assignment_id"]), "title": r["title"],
                 "due_at": r["due_at"].isoformat() if r["due_at"] else None}
                for r in assign_rows
            ]

            return {
                "recent_evidence": recent_evidence,
                "current_modules": current_modules,
                "upcoming_assignments": upcoming,
            }

    async def list_by_course(args: dict[str, Any]) -> dict[str, Any]:
        course_id = uuid.UUID(args["course_id"])
        role = args.get("role")
        async with pool.acquire() as conn:
            # Advisors are not enrolled; they appear with role 'advisor' when
            # assigned (advisor_assignments) to a student enrolled in the course.
            rows = await conn.fetch(
                """SELECT p.id, p.display_name, e.role
                     FROM enrollments e
                     JOIN persons p ON p.id = e.person_id
                    WHERE e.course_node = $1
                      AND ($2::text IS NULL OR e.role = $2)
                   UNION
                   SELECT p.id, p.display_name, 'advisor'
                     FROM advisor_assignments a
                     JOIN enrollments e
                       ON e.person_id = a.student_id
                      AND e.course_node = $1 AND e.role = 'student'
                     JOIN persons p ON p.id = a.advisor_id
                    WHERE ($2::text IS NULL OR $2 = 'advisor')
                   ORDER BY display_name""",
                course_id, role or None,
            )
            return {
                "persons": [
                    {"id": str(r["id"]), "display_name": r["display_name"], "role": r["role"]}
                    for r in rows
                ]
            }

    # ── Conversation persistence ──

    async def save_turn(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        session_id = args.get("session_id")
        role = args.get("role")
        content = args.get("content")
        if not all([person_id, course_id, role, content]):
            return {"error": "person_id, course_id, role, and content are required"}
        async with pool.acquire() as conn:
            turn_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO conversation_turns (id, person_id, course_id, session_id, role, content) VALUES ($1, $2, $3, $4, $5, $6)",
                turn_id, uuid.UUID(person_id), uuid.UUID(course_id),
                uuid.UUID(session_id) if session_id else None,
                role, content,
            )
            return {"id": str(turn_id), "saved": True}

    async def get_recent_turns(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        limit = args.get("limit", 20)
        if not person_id or not course_id:
            return {"error": "person_id and course_id are required"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content, created_at FROM conversation_turns
                   WHERE person_id = $1 AND course_id = $2
                   ORDER BY created_at DESC LIMIT $3""",
                uuid.UUID(person_id), uuid.UUID(course_id), limit,
            )
            # Return in chronological order
            turns = [
                {"role": r["role"], "content": r["content"], "created_at": r["created_at"].isoformat()}
                for r in reversed(rows)
            ]
            return {"turns": turns}

    # ── Learner profile ──

    async def get_learner_profile(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        if not person_id:
            return {"error": "person_id is required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id),
            )
            if not row:
                return {"error": "Person not found"}
            attrs = parse_json_column(row["attributes"])
            return {"profile": attrs.get("learner_profile", ""), "person_id": person_id}

    async def update_learner_profile(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        profile_md = args.get("profile_md")
        if not person_id or profile_md is None:
            return {"error": "person_id and profile_md are required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = parse_json_column(row["attributes"])
            attrs["learner_profile"] = profile_md
            await conn.execute(
                "UPDATE persons SET attributes = $1 WHERE id = $2",
                json.dumps(attrs), uuid.UUID(person_id),
            )
            return {"updated": True}

    # ── Session persistence & queries ──

    async def save_session(args: dict[str, Any]) -> dict[str, Any]:
        session_id = args.get("session_id")
        person_id = args.get("person_id")
        persona = args.get("persona")
        course_id = args.get("course_id")
        if not all([session_id, person_id, persona, course_id]):
            return {"error": "session_id, person_id, persona, and course_id are required"}
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions (id, person_id, persona, course_node, metadata) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO NOTHING",
                uuid.UUID(session_id), uuid.UUID(person_id), persona,
                uuid.UUID(course_id), "{}",
            )
            return {"saved": True}

    async def list_student_sessions(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        if not person_id:
            return {"error": "person_id is required"}
        async with pool.acquire() as conn:
            if course_id:
                rows = await conn.fetch(
                    """SELECT s.id, s.persona, s.course_node, s.created_at,
                              n.title as course_title,
                              (SELECT COUNT(*) FROM conversation_turns ct WHERE ct.session_id = s.id) as turn_count,
                              (SELECT content FROM conversation_turns ct WHERE ct.session_id = s.id AND ct.role = 'user' ORDER BY ct.created_at LIMIT 1) as first_message
                       FROM sessions s
                       LEFT JOIN nodes n ON n.id = s.course_node
                       WHERE s.person_id = $1 AND s.course_node = $2 AND s.persona = 'student'
                       ORDER BY s.created_at DESC""",
                    uuid.UUID(person_id), uuid.UUID(course_id),
                )
            else:
                rows = await conn.fetch(
                    """SELECT s.id, s.persona, s.course_node, s.created_at,
                              n.title as course_title,
                              (SELECT COUNT(*) FROM conversation_turns ct WHERE ct.session_id = s.id) as turn_count,
                              (SELECT content FROM conversation_turns ct WHERE ct.session_id = s.id AND ct.role = 'user' ORDER BY ct.created_at LIMIT 1) as first_message
                       FROM sessions s
                       LEFT JOIN nodes n ON n.id = s.course_node
                       WHERE s.person_id = $1 AND s.persona = 'student'
                       ORDER BY s.created_at DESC""",
                    uuid.UUID(person_id),
                )
            return {
                "sessions": [
                    {
                        "session_id": str(r["id"]),
                        "course_id": str(r["course_node"]) if r["course_node"] else None,
                        "course_title": r["course_title"] or "Unknown",
                        "created_at": r["created_at"].isoformat(),
                        "turn_count": r["turn_count"],
                        "first_message": (r["first_message"] or "")[:100],
                    }
                    for r in rows
                ]
            }

    async def get_session_transcript(args: dict[str, Any]) -> dict[str, Any]:
        session_id = args.get("session_id")
        if not session_id:
            return {"error": "session_id is required"}
        async with pool.acquire() as conn:
            # Get session info
            session_row = await conn.fetchrow(
                """SELECT s.id, s.person_id, s.course_node, s.created_at, p.display_name, n.title as course_title
                   FROM sessions s
                   JOIN persons p ON p.id = s.person_id
                   LEFT JOIN nodes n ON n.id = s.course_node
                   WHERE s.id = $1""",
                uuid.UUID(session_id),
            )
            if not session_row:
                return {"error": "Session not found"}
            # Get turns
            rows = await conn.fetch(
                """SELECT role, content, created_at FROM conversation_turns
                   WHERE session_id = $1 ORDER BY created_at""",
                uuid.UUID(session_id),
            )
            return {
                "session_id": str(session_row["id"]),
                "student_name": session_row["display_name"],
                "course_title": session_row["course_title"] or "Unknown",
                "created_at": session_row["created_at"].isoformat(),
                "turns": [
                    {"role": r["role"], "content": r["content"], "created_at": r["created_at"].isoformat()}
                    for r in rows
                ],
            }

    # ── Retrieval practice / concept reviews ──

    async def save_concept_review(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        concept_id = args.get("concept_id")
        session_id = args.get("session_id")
        outcome = args.get("outcome")
        if not all([person_id, concept_id, outcome]):
            return {"error": "person_id, concept_id, and outcome are required"}
        async with pool.acquire() as conn:
            cid = await resolve_concept_id(conn, concept_id)
            if cid is None:
                return {"error": f"Concept not found: {concept_id}"}
            await conn.execute(
                """INSERT INTO concept_reviews (person_id, concept_id, session_id, outcome)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (person_id, concept_id, session_id) DO UPDATE SET outcome = $4, reviewed_at = now()""",
                uuid.UUID(person_id), cid,
                uuid.UUID(session_id) if session_id else None, outcome,
            )
            return {"saved": True}

    async def get_review_candidates(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        limit = args.get("limit", 3)
        if not person_id or not course_id:
            return {"error": "person_id and course_id are required"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT a.node_id, n.title,
                          (SELECT MAX(cr.reviewed_at) FROM concept_reviews cr WHERE cr.person_id = $1 AND cr.concept_id = a.node_id) as last_reviewed
                   FROM attestations a
                   JOIN nodes n ON n.id = a.node_id
                   JOIN edges e ON e.from_node = n.id AND e.kind = 'part_of'
                   JOIN nodes mod ON mod.id = e.to_node AND mod.kind = 'module'
                   JOIN edges e2 ON e2.from_node = mod.id AND e2.kind = 'part_of'
                   WHERE a.person_id = $1 AND a.level = 'proficient'
                   AND e2.to_node = $2
                   ORDER BY last_reviewed NULLS FIRST, a.issued_at ASC
                   LIMIT $3""",
                uuid.UUID(person_id), uuid.UUID(course_id), limit,
            )
            return {
                "concepts": [
                    {"id": str(r["node_id"]), "title": r["title"], "last_reviewed": r["last_reviewed"].isoformat() if r["last_reviewed"] else None}
                    for r in rows
                ]
            }

    # ── Goals ──

    async def get_goals(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        if not person_id:
            return {"error": "person_id is required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = parse_json_column(row["attributes"])
            return {"goals": attrs.get("goals", [])}

    async def set_goal(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        description = args.get("description")
        target_date = args.get("target_date")
        if not person_id or not description:
            return {"error": "person_id and description are required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = parse_json_column(row["attributes"])
            goals = attrs.get("goals", [])
            goals.append({
                "description": description,
                "target_date": target_date,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "active",
            })
            attrs["goals"] = goals
            await conn.execute("UPDATE persons SET attributes = $1 WHERE id = $2", json.dumps(attrs), uuid.UUID(person_id))
            return {"saved": True}

    # ── Student insights & session summary ──

    async def update_student_insights(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        insights = args.get("insights")
        if not person_id or insights is None:
            return {"error": "person_id and insights are required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = parse_json_column(row["attributes"])
            attrs["student_insights"] = insights
            await conn.execute("UPDATE persons SET attributes = $1 WHERE id = $2", json.dumps(attrs), uuid.UUID(person_id))
            return {"updated": True}

    async def update_session_summary(args: dict[str, Any]) -> dict[str, Any]:
        session_id = args.get("session_id")
        summary = args.get("summary")
        review_flag = args.get("review_flag", False)
        review_reason = args.get("review_reason")
        if not session_id or not summary:
            return {"error": "session_id and summary are required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT metadata FROM sessions WHERE id = $1", uuid.UUID(session_id))
            if not row:
                return {"error": "Session not found"}
            metadata = parse_json_column(row["metadata"])
            metadata["summary"] = summary
            metadata["review_flag"] = review_flag
            if review_reason:
                metadata["review_reason"] = review_reason
            await conn.execute("UPDATE sessions SET metadata = $1 WHERE id = $2", json.dumps(metadata), uuid.UUID(session_id))
            return {"updated": True}

    return [
        ToolDef(
            name="roster.get",
            description="Get a person by ID",
            input_schema={"type": "object", "properties": {"person_id": {"type": "string"}}, "required": ["person_id"]},
            handler=get,
        ),
        ToolDef(
            name="roster.get_student",
            description="Get student profile with optional enrollment status",
            input_schema={"type": "object", "properties": {"person_id": {"type": "string"}, "course_id": {"type": "string"}}, "required": ["person_id"]},
            handler=get_student,
        ),
        ToolDef(
            name="roster.get_student_context",
            description="Get student context: recent evidence, modules, upcoming assignments",
            input_schema={"type": "object", "properties": {"person_id": {"type": "string"}, "course_id": {"type": "string"}}, "required": ["person_id", "course_id"]},
            handler=get_student_context,
        ),
        ToolDef(
            name="roster.list_by_course",
            description="List persons enrolled in a course",
            input_schema={"type": "object", "properties": {"course_id": {"type": "string"}, "role": {"type": "string"}}, "required": ["course_id"]},
            handler=list_by_course,
        ),
        ToolDef(
            name="roster.save_turn",
            description="Save a conversation turn for persistence across sessions",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"},
                "session_id": {"type": "string"}, "role": {"type": "string"}, "content": {"type": "string"},
            }, "required": ["person_id", "course_id", "role", "content"]},
            handler=save_turn, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.get_recent_turns",
            description="Get recent conversation turns for a student in a course",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"},
                "limit": {"type": "integer"},
            }, "required": ["person_id", "course_id"]},
            handler=get_recent_turns, mutates=False,
        ),
        ToolDef(
            name="roster.get_learner_profile",
            description="Get a student's learner profile — persistent observations about how they learn",
            input_schema={"type": "object", "properties": {"person_id": {"type": "string"}}, "required": ["person_id"]},
            handler=get_learner_profile, mutates=False,
        ),
        ToolDef(
            name="roster.update_learner_profile",
            description="Update a student's learner profile with new observations about their learning style",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "profile_md": {"type": "string"},
            }, "required": ["person_id", "profile_md"]},
            handler=update_learner_profile, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.save_session",
            description="Persist a session to the database",
            input_schema={"type": "object", "properties": {
                "session_id": {"type": "string"}, "person_id": {"type": "string"},
                "persona": {"type": "string"}, "course_id": {"type": "string"},
            }, "required": ["session_id", "person_id", "persona", "course_id"]},
            handler=save_session, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.list_student_sessions",
            description="List tutoring sessions for a student, optionally filtered by course",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"},
            }, "required": ["person_id"]},
            handler=list_student_sessions, mutates=False,
        ),
        ToolDef(
            name="roster.get_session_transcript",
            description="Get the full conversation transcript for a session",
            input_schema={"type": "object", "properties": {
                "session_id": {"type": "string"},
            }, "required": ["session_id"]},
            handler=get_session_transcript, mutates=False,
        ),
        ToolDef(
            name="roster.save_concept_review",
            description="Record a concept review outcome for retrieval practice tracking",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "concept_id": {"type": "string"},
                "session_id": {"type": "string"}, "outcome": {"type": "string", "enum": ["recalled", "struggled", "failed"]},
            }, "required": ["person_id", "concept_id", "outcome"]},
            handler=save_concept_review, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.get_review_candidates",
            description="Get proficient concepts sorted by least-recently-reviewed for retrieval practice",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"}, "limit": {"type": "integer"},
            }, "required": ["person_id", "course_id"]},
            handler=get_review_candidates, mutates=False,
        ),
        ToolDef(
            name="roster.get_goals",
            description="Get a student's active learning goals",
            input_schema={"type": "object", "properties": {"person_id": {"type": "string"}}, "required": ["person_id"]},
            handler=get_goals, mutates=False,
        ),
        ToolDef(
            name="roster.set_goal",
            description="Set a learning goal for a student",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "description": {"type": "string"}, "target_date": {"type": "string"},
            }, "required": ["person_id", "description"]},
            handler=set_goal, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.update_student_insights",
            description="Update student-facing learning insights (written by learning analyst)",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "insights": {"type": "array", "items": {"type": "string"}},
            }, "required": ["person_id", "insights"]},
            handler=update_student_insights, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.update_session_summary",
            description="Update session summary and review flag (written by learning analyst)",
            input_schema={"type": "object", "properties": {
                "session_id": {"type": "string"}, "summary": {"type": "string"},
                "review_flag": {"type": "boolean"}, "review_reason": {"type": "string"},
            }, "required": ["session_id", "summary"]},
            handler=update_session_summary, mutates=True, requires_approval=False,
        ),
    ]
