"""Who is asking, as far as the assessments server can tell from `requester_id`.

The tool gateway overwrites `requester_id` with the signed-in caller whenever the argument is
present, so it can be trusted when given. An absent or unknown requester gets the narrowest
view (a learner's), never a staff one.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import asyncpg


@dataclass(frozen=True)
class Viewer:
    person_id: uuid.UUID | None
    roles: frozenset[str] = frozenset()
    faculty_courses: frozenset[str] = field(default_factory=frozenset)
    student_courses: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def is_staff_for(self, course_id: str | None, *, draft: bool = False) -> bool:
        """May see unreleased feedback and uncommitted scores in this course. A draft's
        unreleased feedback is for the course's faculty only, not admins (spec.md §12.5)."""
        if course_id is not None and course_id in self.faculty_courses:
            return True
        return self.is_admin and not draft


ANONYMOUS = Viewer(None)


async def load_viewer(conn: asyncpg.Connection, requester_id: uuid.UUID | None) -> Viewer:
    if requester_id is None:
        return ANONYMOUS
    roles = await conn.fetchval("SELECT roles FROM persons WHERE id = $1", requester_id)
    if roles is None:
        return ANONYMOUS
    rows = await conn.fetch(
        """SELECT course_node::text AS course, role FROM enrollments
           WHERE person_id = $1 AND status = 'active' AND role IN ('faculty', 'student')""",
        requester_id,
    )
    return Viewer(
        requester_id,
        frozenset(roles),
        frozenset(r["course"] for r in rows if r["role"] == "faculty"),
        frozenset(r["course"] for r in rows if r["role"] == "student"),
    )
