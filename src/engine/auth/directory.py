"""Identity-adjacent reads that object-level authorization needs.

`ScopeDirectory` is the seam scope checks depend on; `PgScopeDirectory` reads the
engine-visible tables (nodes, enrollments, advisor_assignments, sessions,
pending_credentials) directly. Ids cross this boundary as strings; a malformed
id is treated as unknown rather than raising.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import asyncpg

from engine.auth.repository import course_slug


@dataclass(frozen=True)
class CourseRef:
    id: str
    slug: str
    title: str


@dataclass(frozen=True)
class SessionOwner:
    person_id: str
    course_id: str | None


class ScopeDirectory(Protocol):
    async def resolve_course(self, ref: str) -> CourseRef | None:
        """A course node by UUID or slug (metadata.slug, else derived from the title)."""
        ...

    async def list_courses(self) -> list[CourseRef]:
        """Every course node, ordered by title."""
        ...

    async def student_course_ids(self, person_id: str) -> frozenset[str]:
        """Courses with an active `student` enrollment for this person."""
        ...

    async def course_ids_with_students(self, student_ids: Iterable[str]) -> frozenset[str]:
        """Courses where any of these people has an active `student` enrollment."""
        ...

    async def session_owner(self, session_id: str) -> SessionOwner | None:
        """The persisted tutoring session's person and course."""
        ...

    async def pending_credential_course(self, pending_id: str) -> str | None: ...

    async def program_course_ids(self, lead_id: str) -> frozenset[str] | None:
        """Courses in programs whose metadata.program_lead_ids lists this person.

        None when no program names them, i.e. their program cannot be determined.
        """
        ...

    async def count_persons_with_role(self, role: str) -> int: ...


def _uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


class PgScopeDirectory:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_courses(self) -> list[CourseRef]:
        rows = await self._pool.fetch(
            "SELECT id, title, metadata->>'slug' AS slug FROM nodes "
            "WHERE kind = 'course' ORDER BY title"
        )
        return [
            CourseRef(str(r["id"]), course_slug(r["title"], r["slug"]), r["title"]) for r in rows
        ]

    async def resolve_course(self, ref: str) -> CourseRef | None:
        wanted_id = _uuid(ref)
        wanted_slug = ref.strip().lower()
        for course in await self.list_courses():
            if course.id == wanted_id or course.slug.lower() == wanted_slug:
                return course
        return None

    async def student_course_ids(self, person_id: str) -> frozenset[str]:
        pid = _uuid(person_id)
        if pid is None:
            return frozenset()
        rows = await self._pool.fetch(
            "SELECT DISTINCT course_node FROM enrollments "
            "WHERE person_id = $1::uuid AND role = 'student' AND status = 'active'",
            pid,
        )
        return frozenset(str(r["course_node"]) for r in rows)

    async def course_ids_with_students(self, student_ids: Iterable[str]) -> frozenset[str]:
        ids = [u for u in (_uuid(s) for s in student_ids) if u is not None]
        if not ids:
            return frozenset()
        rows = await self._pool.fetch(
            "SELECT DISTINCT course_node FROM enrollments "
            "WHERE person_id = ANY($1::uuid[]) AND role = 'student' AND status = 'active'",
            ids,
        )
        return frozenset(str(r["course_node"]) for r in rows)

    async def session_owner(self, session_id: str) -> SessionOwner | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT person_id, course_node FROM sessions WHERE id = $1::uuid", sid
        )
        if row is None:
            return None
        course = row["course_node"]
        return SessionOwner(str(row["person_id"]), str(course) if course else None)

    async def pending_credential_course(self, pending_id: str) -> str | None:
        pid = _uuid(pending_id)
        if pid is None:
            return None
        course = await self._pool.fetchval(
            "SELECT course_id FROM pending_credentials WHERE id = $1::uuid", pid
        )
        return str(course) if course else None

    async def program_course_ids(self, lead_id: str) -> frozenset[str] | None:
        lid = _uuid(lead_id)
        if lid is None:
            return None
        programs = await self._pool.fetch(
            "SELECT id FROM nodes WHERE kind = 'program' "
            "AND COALESCE(metadata->'program_lead_ids', '[]'::jsonb) ? $1",
            lid,
        )
        if not programs:
            return None
        rows = await self._pool.fetch(
            "SELECT DISTINCT c.id FROM edges e JOIN nodes c ON c.id = e.from_node "
            "WHERE e.kind = 'part_of' AND c.kind = 'course' AND e.to_node = ANY($1::uuid[])",
            [r["id"] for r in programs],
        )
        return frozenset(str(r["id"]) for r in rows)

    async def count_persons_with_role(self, role: str) -> int:
        count = await self._pool.fetchval(
            "SELECT count(*) FROM persons WHERE $1 = ANY(roles)", role
        )
        return int(count or 0)
