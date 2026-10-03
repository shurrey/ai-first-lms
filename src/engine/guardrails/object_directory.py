"""Course lookups for objects the gateway scope-checks but no MCP read resolves to a course.

Ids cross this boundary as strings; a malformed or unknown id resolves to None.
"""

from __future__ import annotations

import uuid
from typing import Protocol

import asyncpg


class ObjectDirectory(Protocol):
    async def submission_course(self, submission_id: str) -> str | None:
        """The submission's course: submissions.course_node, else its assignment's
        metadata.course_id."""
        ...

    async def question_bank_course(self, bank_id: str) -> str | None: ...

    async def criterion_course(self, criterion_id: str) -> str | None:
        """The course of the assignment whose rubric holds the criterion."""
        ...

    async def node_course(self, node_id: str) -> str | None:
        """A course node itself, else the node's metadata.course_id (assignments, outcomes)."""
        ...


def _uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


class PgObjectDirectory:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def submission_course(self, submission_id: str) -> str | None:
        sid = _uuid(submission_id)
        if sid is None:
            return None
        course = await self._pool.fetchval(
            "SELECT COALESCE(s.course_node::text, a.metadata->>'course_id') "
            "FROM submissions s LEFT JOIN nodes a ON a.id = s.assignment_node "
            "WHERE s.id = $1::uuid",
            sid,
        )
        return _uuid(course) if course else None

    async def question_bank_course(self, bank_id: str) -> str | None:
        bid = _uuid(bank_id)
        if bid is None:
            return None
        course = await self._pool.fetchval(
            "SELECT course_node FROM question_banks WHERE id = $1::uuid", bid
        )
        return str(course) if course else None

    async def criterion_course(self, criterion_id: str) -> str | None:
        cid = _uuid(criterion_id)
        if cid is None:
            return None
        course = await self._pool.fetchval(
            "SELECT a.metadata->>'course_id' FROM rubric_criteria rc "
            "JOIN nodes a ON a.metadata->>'rubric_id' = rc.rubric_id::text "
            "WHERE rc.id = $1::uuid AND a.metadata ? 'course_id' "
            "ORDER BY a.id LIMIT 1",
            cid,
        )
        return _uuid(course) if course else None

    async def node_course(self, node_id: str) -> str | None:
        nid = _uuid(node_id)
        if nid is None:
            return None
        course = await self._pool.fetchval(
            "SELECT CASE WHEN kind = 'course' THEN id::text ELSE metadata->>'course_id' END "
            "FROM nodes WHERE id = $1::uuid",
            nid,
        )
        return _uuid(course) if course else None
