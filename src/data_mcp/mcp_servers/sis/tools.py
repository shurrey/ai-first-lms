"""SIS (Student Information System) MCP server tool handlers."""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef

# Grade-point mapping for synthetic GPA calculation
_GRADE_POINTS: dict[str, float] = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0, "D-": 0.7,
    "F": 0.0,
}

# Synthetic letter grades derived from a numeric score (0-1 scale)
def _letter_grade(score: float) -> str:
    if score >= 0.97:
        return "A+"
    if score >= 0.93:
        return "A"
    if score >= 0.90:
        return "A-"
    if score >= 0.87:
        return "B+"
    if score >= 0.83:
        return "B"
    if score >= 0.80:
        return "B-"
    if score >= 0.77:
        return "C+"
    if score >= 0.73:
        return "C"
    if score >= 0.70:
        return "C-"
    if score >= 0.67:
        return "D+"
    if score >= 0.60:
        return "D"
    return "F"


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all SIS server tool definitions."""

    # ------------------------------------------------------------------
    # sis.get_transcript
    # ------------------------------------------------------------------
    async def get_transcript(args: dict[str, Any]) -> dict[str, Any]:
        student_id = args.get("student_id")
        if not student_id:
            return {"error": "student_id is required"}

        try:
            sid = uuid.UUID(student_id)
        except ValueError:
            return {"error": "Invalid student_id UUID"}

        async with pool.acquire() as conn:
            # Verify student exists
            person = await conn.fetchrow(
                "SELECT id, display_name FROM persons WHERE id = $1", sid
            )
            if not person:
                return {"error": "Student not found"}

            # Pull enrollments joined to course nodes; derive grade from
            # average evidence score for that course.
            rows = await conn.fetch(
                """
                SELECT
                    n.title                                   AS course_title,
                    e.enrolled_at                             AS enrolled_at,
                    COALESCE(
                        AVG(ev.score) FILTER (WHERE ev.score IS NOT NULL),
                        NULL
                    )                                          AS avg_score,
                    n.metadata->>'credits'                    AS credits_raw,
                    n.metadata->>'term'                       AS term
                FROM enrollments e
                JOIN nodes n ON n.id = e.course_node
                LEFT JOIN evidence ev
                       ON ev.person_id = e.person_id
                      AND ev.node_id   = e.course_node
                WHERE e.person_id = $1
                  AND n.kind = 'course'
                GROUP BY n.title, e.enrolled_at, n.metadata->>'credits', n.metadata->>'term'
                ORDER BY e.enrolled_at
                """,
                sid,
            )

            courses = []
            total_points = 0.0
            total_credits = 0.0

            for r in rows:
                credits = float(r["credits_raw"]) if r["credits_raw"] else 3.0
                term = r["term"] or "Fall 2025"
                avg = r["avg_score"]
                if avg is not None:
                    grade = _letter_grade(float(avg))
                else:
                    grade = "IP"  # In Progress

                gp = _GRADE_POINTS.get(grade, 0.0)
                total_points += gp * credits
                total_credits += credits

                courses.append({
                    "term": term,
                    "title": r["course_title"],
                    "grade": grade,
                    "credits": credits,
                })

            gpa = round(total_points / total_credits, 2) if total_credits > 0 else 0.0
            credits_earned = sum(
                c["credits"] for c in courses if c["grade"] not in ("F", "IP")
            )

            return {
                "courses": courses,
                "gpa": gpa,
                "credits_earned": credits_earned,
            }

    # ------------------------------------------------------------------
    # sis.degree_audit
    # ------------------------------------------------------------------
    async def degree_audit(args: dict[str, Any]) -> dict[str, Any]:
        student_id = args.get("student_id")
        program_id = args.get("program_id")

        if not student_id:
            return {"error": "student_id is required"}

        try:
            sid = uuid.UUID(student_id)
        except ValueError:
            return {"error": "Invalid student_id UUID"}

        async with pool.acquire() as conn:
            person = await conn.fetchrow(
                "SELECT id, display_name FROM persons WHERE id = $1", sid
            )
            if not person:
                return {"error": "Student not found"}

            # Count completed courses (evidence with score >= 0.6)
            enrolled = await conn.fetch(
                """
                SELECT
                    n.id          AS course_id,
                    n.title       AS title,
                    n.metadata->>'credits' AS credits_raw,
                    COALESCE(AVG(ev.score) FILTER (WHERE ev.score IS NOT NULL), NULL) AS avg_score
                FROM enrollments e
                JOIN nodes n ON n.id = e.course_node AND n.kind = 'course'
                LEFT JOIN evidence ev
                       ON ev.person_id = e.person_id AND ev.node_id = e.course_node
                WHERE e.person_id = $1
                GROUP BY n.id, n.title, n.metadata->>'credits'
                """,
                sid,
            )

        # Synthetic CS program requirements
        program = program_id or "CS-BS"
        requirements = [
            {"id": "core-cs",    "name": "CS Core (12 credits)",   "credits_required": 12},
            {"id": "math",       "name": "Mathematics (6 credits)", "credits_required": 6},
            {"id": "electives",  "name": "Electives (9 credits)",   "credits_required": 9},
            {"id": "capstone",   "name": "Capstone (3 credits)",    "credits_required": 3},
        ]
        total_required = sum(r["credits_required"] for r in requirements)

        credits_completed = sum(
            float(r["credits_raw"] or 3.0)
            for r in enrolled
            if r["avg_score"] is not None and float(r["avg_score"]) >= 0.6
        )

        satisfied = credits_completed >= total_required
        remaining_credits = max(0.0, total_required - credits_completed)

        # Rough projected graduation: 1 term per 15 credits remaining
        terms_remaining = max(1, int(remaining_credits / 15) + 1) if remaining_credits > 0 else 0
        projected = f"{'Spring' if terms_remaining % 2 == 0 else 'Fall'} {2026 + terms_remaining // 2}"

        req_details = []
        accum = 0.0
        for req in requirements:
            needed = float(req["credits_required"])
            applied = min(needed, max(0.0, credits_completed - accum))
            accum += applied
            req_details.append({
                "id": req["id"],
                "name": req["name"],
                "credits_required": needed,
                "credits_applied": round(applied, 1),
                "satisfied": applied >= needed,
            })

        return {
            "program": program,
            "requirements": req_details,
            "satisfied": satisfied,
            "remaining": round(remaining_credits, 1),
            "projected_graduation": projected if not satisfied else "Eligible now",
        }

    # ------------------------------------------------------------------
    # sis.check_prerequisites
    # ------------------------------------------------------------------
    async def check_prerequisites(args: dict[str, Any]) -> dict[str, Any]:
        student_id = args.get("student_id")
        course_id = args.get("course_id")

        if not student_id or not course_id:
            return {"error": "student_id and course_id are required"}

        try:
            sid = uuid.UUID(student_id)
            cid = uuid.UUID(course_id)
        except ValueError:
            return {"error": "Invalid UUID"}

        async with pool.acquire() as conn:
            person = await conn.fetchrow("SELECT id FROM persons WHERE id = $1", sid)
            if not person:
                return {"error": "Student not found"}

            course = await conn.fetchrow(
                "SELECT id, title FROM nodes WHERE id = $1 AND kind = 'course'", cid
            )
            if not course:
                return {"error": "Course not found"}

            # Prerequisite edges: prerequisite_of means from_node must be
            # completed before to_node. So look for edges where to_node = cid
            # and kind = 'prerequisite_of'.
            prereq_rows = await conn.fetch(
                """
                SELECT n.id AS prereq_id, n.title AS prereq_title
                FROM edges e
                JOIN nodes n ON n.id = e.from_node
                WHERE e.to_node = $1 AND e.kind = 'prerequisite_of'
                """,
                cid,
            )

            if not prereq_rows:
                return {"ok": True, "missing": []}

            # Check which prerequisites the student has completed
            completed_nodes = await conn.fetch(
                """
                SELECT DISTINCT e.course_node
                FROM enrollments e
                WHERE e.person_id = $1 AND e.status = 'completed'
                """,
                sid,
            )
            completed_ids = {str(r["course_node"]) for r in completed_nodes}

            # Also consider courses where average evidence score >= 0.6
            evidence_passed = await conn.fetch(
                """
                SELECT ev.node_id
                FROM evidence ev
                WHERE ev.person_id = $1
                GROUP BY ev.node_id
                HAVING AVG(ev.score) FILTER (WHERE ev.score IS NOT NULL) >= 0.6
                """,
                sid,
            )
            passed_ids = completed_ids | {str(r["node_id"]) for r in evidence_passed}

            missing = [
                {"id": str(r["prereq_id"]), "title": r["prereq_title"]}
                for r in prereq_rows
                if str(r["prereq_id"]) not in passed_ids
            ]

            return {"ok": len(missing) == 0, "missing": missing}

    # ------------------------------------------------------------------
    # sis.catalog_search
    # ------------------------------------------------------------------
    async def catalog_search(args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        subject = args.get("subject")
        level = args.get("level")
        term = args.get("term")

        async with pool.acquire() as conn:
            conditions: list[str] = ["n.kind = 'course'"]
            params: list[Any] = []
            idx = 1

            if query:
                conditions.append(f"(n.title ILIKE ${idx} OR n.description ILIKE ${idx})")
                params.append(f"%{query}%")
                idx += 1

            if subject:
                conditions.append(f"n.tags @> ARRAY[${idx}::text]")
                params.append(subject.lower())
                idx += 1

            if level:
                conditions.append(f"n.metadata->>'level' = ${idx}")
                params.append(str(level))
                idx += 1

            if term:
                conditions.append(f"n.metadata->>'term' = ${idx}")
                params.append(term)
                idx += 1

            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"""
                SELECT
                    n.id                            AS course_id,
                    n.title                         AS title,
                    n.description                   AS description,
                    n.metadata->>'credits'          AS credits,
                    n.metadata->>'term'             AS term,
                    n.metadata->>'level'            AS level,
                    n.tags                          AS tags
                FROM nodes n
                WHERE {where}
                ORDER BY n.title
                LIMIT 50
                """,
                *params,
            )

            return {
                "courses": [
                    {
                        "id": str(r["course_id"]),
                        "title": r["title"],
                        "description": r["description"] or "",
                        "credits": float(r["credits"]) if r["credits"] else 3.0,
                        "term": r["term"] or "",
                        "level": r["level"] or "",
                        "tags": list(r["tags"] or []),
                    }
                    for r in rows
                ]
            }

    # ------------------------------------------------------------------
    # sis.schedule_availability
    # ------------------------------------------------------------------
    async def schedule_availability(args: dict[str, Any]) -> dict[str, Any]:
        student_id = args.get("student_id")
        term = args.get("term")
        course_ids = args.get("course_ids", [])

        if not student_id or not term:
            return {"error": "student_id and term are required"}

        if not course_ids:
            return {"feasible": True, "sections": [], "conflicts": []}

        try:
            sid = uuid.UUID(student_id)
            cid_list = [uuid.UUID(c) for c in course_ids]
        except ValueError:
            return {"error": "Invalid UUID in student_id or course_ids"}

        async with pool.acquire() as conn:
            person = await conn.fetchrow("SELECT id FROM persons WHERE id = $1", sid)
            if not person:
                return {"error": "Student not found"}

            # Get course details for requested courses
            rows = await conn.fetch(
                """
                SELECT
                    n.id       AS course_id,
                    n.title    AS title,
                    n.metadata AS metadata
                FROM nodes n
                WHERE n.id = ANY($1::uuid[]) AND n.kind = 'course'
                """,
                cid_list,
            )

            found_ids = {str(r["course_id"]) for r in rows}
            not_found = [str(c) for c in cid_list if str(c) not in found_ids]

            if not_found:
                return {
                    "error": f"Courses not found: {not_found}",
                    "feasible": False,
                    "sections": [],
                    "conflicts": [],
                }

            # Check if student is already enrolled in any of these courses
            already_enrolled = await conn.fetch(
                """
                SELECT e.course_node
                FROM enrollments e
                WHERE e.person_id = $1
                  AND e.course_node = ANY($2::uuid[])
                  AND e.status = 'active'
                """,
                sid,
                cid_list,
            )
            enrolled_ids = {str(r["course_node"]) for r in already_enrolled}

            # Build synthetic section schedule from metadata
            import json as _json

            sections = []
            conflicts: list[dict[str, Any]] = []

            for r in rows:
                meta = r["metadata"] or {}
                # Synthetic schedule: use metadata if present, otherwise generate
                schedule = meta.get("schedule") if isinstance(meta, dict) else None
                if not schedule:
                    # Deterministic synthetic schedule based on course title hash
                    days_options = [["Mon", "Wed", "Fri"], ["Tue", "Thu"], ["Mon", "Wed"]]
                    day_idx = hash(str(r["course_id"])) % len(days_options)
                    hour = 8 + (hash(r["title"]) % 10)
                    schedule = {
                        "days": days_options[day_idx],
                        "start_time": f"{hour:02d}:00",
                        "end_time": f"{hour + 1:02d}:20",
                        "location": "Online",
                    }

                sections.append({
                    "course_id": str(r["course_id"]),
                    "title": r["title"],
                    "term": term,
                    "schedule": schedule,
                    "already_enrolled": str(r["course_id"]) in enrolled_ids,
                    "seats_available": 25,  # synthetic
                })

            # Detect time conflicts among sections being requested
            seen_slots: list[tuple[str, str, str]] = []  # (day, start, course_id)
            for sec in sections:
                sched = sec["schedule"]
                for day in sched.get("days", []):
                    slot_key = (day, sched.get("start_time", ""))
                    for prev_day, prev_start, prev_cid in seen_slots:
                        if prev_day == day and prev_start == sched.get("start_time"):
                            conflicts.append({
                                "course_a": prev_cid,
                                "course_b": sec["course_id"],
                                "day": day,
                                "time": prev_start,
                            })
                    seen_slots.append((day, sched.get("start_time", ""), sec["course_id"]))

            feasible = len(conflicts) == 0

            return {
                "feasible": feasible,
                "sections": sections,
                "conflicts": conflicts,
            }

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------
    return [
        ToolDef(
            name="sis.get_transcript",
            description="Retrieve a student's academic transcript with grades and GPA",
            input_schema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string", "description": "UUID of the student"},
                },
                "required": ["student_id"],
            },
            handler=get_transcript,
        ),
        ToolDef(
            name="sis.degree_audit",
            description="Run a degree audit for a student against a program's requirements",
            input_schema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string", "description": "UUID of the student"},
                    "program_id": {"type": "string", "description": "Program identifier (optional)"},
                },
                "required": ["student_id"],
            },
            handler=degree_audit,
        ),
        ToolDef(
            name="sis.check_prerequisites",
            description="Check whether a student has satisfied prerequisites for a course",
            input_schema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string", "description": "UUID of the student"},
                    "course_id":  {"type": "string", "description": "UUID of the course"},
                },
                "required": ["student_id", "course_id"],
            },
            handler=check_prerequisites,
        ),
        ToolDef(
            name="sis.catalog_search",
            description="Search the course catalog by query, subject, level, or term",
            input_schema={
                "type": "object",
                "properties": {
                    "query":   {"type": "string"},
                    "subject": {"type": "string"},
                    "level":   {"type": "string"},
                    "term":    {"type": "string"},
                },
            },
            handler=catalog_search,
        ),
        ToolDef(
            name="sis.schedule_availability",
            description="Check schedule feasibility for a student and a set of courses in a term",
            input_schema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string"},
                    "term":       {"type": "string"},
                    "course_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of course UUIDs to check",
                    },
                },
                "required": ["student_id", "term", "course_ids"],
            },
            handler=schedule_availability,
        ),
    ]
