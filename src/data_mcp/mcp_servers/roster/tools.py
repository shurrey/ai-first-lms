"""Roster MCP server tool handlers."""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef


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
                   ORDER BY e.observed_at DESC LIMIT 10""",
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
                   ORDER BY (m.metadata->>'order')::int""",
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
                   ORDER BY a.due_at LIMIT 5""",
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
            if role:
                rows = await conn.fetch(
                    """SELECT p.id, p.display_name, e.role
                       FROM enrollments e
                       JOIN persons p ON p.id = e.person_id
                       WHERE e.course_node = $1 AND e.role = $2
                       ORDER BY p.display_name""",
                    course_id, role,
                )
            else:
                rows = await conn.fetch(
                    """SELECT p.id, p.display_name, e.role
                       FROM enrollments e
                       JOIN persons p ON p.id = e.person_id
                       WHERE e.course_node = $1
                       ORDER BY p.display_name""",
                    course_id,
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
        role = args.get("role")
        content = args.get("content")
        if not all([person_id, course_id, role, content]):
            return {"error": "person_id, course_id, role, and content are required"}
        async with pool.acquire() as conn:
            turn_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO conversation_turns (id, person_id, course_id, role, content) VALUES ($1, $2, $3, $4, $5)",
                turn_id, uuid.UUID(person_id), uuid.UUID(course_id), role, content,
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
            attrs = row["attributes"] or {}
            import json
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            return {"profile": attrs.get("learner_profile", ""), "person_id": person_id}

    async def update_learner_profile(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        profile_md = args.get("profile_md")
        if not person_id or profile_md is None:
            return {"error": "person_id and profile_md are required"}
        async with pool.acquire() as conn:
            import json
            # Get current attributes
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = row["attributes"] or {}
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            attrs["learner_profile"] = profile_md
            await conn.execute(
                "UPDATE persons SET attributes = $1 WHERE id = $2",
                json.dumps(attrs), uuid.UUID(person_id),
            )
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
                "role": {"type": "string"}, "content": {"type": "string"},
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
    ]
