"""data_access_log: who read a learner's sensitive data (spec.md §12.3).

Rows are written by `scope.can_view_student`; this module only stores and lists them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import asyncpg

AccessResource = Literal["transcript", "profile", "analyst_summary", "submission",
                         "ai_actions"]


@dataclass(frozen=True)
class AccessEntry:
    actor_id: str
    subject_id: str
    resource: AccessResource
    resource_id: str | None  # None when the resource is the person (profile)
    purpose: str


@dataclass(frozen=True)
class AccessRow:
    id: int
    actor_id: str
    subject_id: str
    resource: str
    resource_id: str | None
    purpose: str | None
    created_at: datetime


class AccessLog(Protocol):
    async def record(self, entry: AccessEntry) -> None:
        """Raises on a storage failure; the caller decides whether that fails the request."""
        ...

    async def record_many(self, entries: list[AccessEntry]) -> None:
        """All rows in one statement; raises like `record`."""
        ...

    async def list_by_subject(
        self, subject_id: str, *, limit: int = 100, before: datetime | None = None
    ) -> list[AccessRow]:
        """Newest first; `before` pages backwards by created_at."""
        ...


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


class PgAccessLog:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(self, entry: AccessEntry) -> None:
        """A resource_id that is not a UUID is stored as null (the column is uuid)."""
        await self._pool.execute(
            "INSERT INTO data_access_log (actor_id, subject_id, resource, resource_id, purpose) "
            "VALUES ($1, $2, $3, $4, $5)",
            uuid.UUID(entry.actor_id),
            uuid.UUID(entry.subject_id),
            entry.resource,
            _uuid_or_none(entry.resource_id),
            entry.purpose,
        )

    async def record_many(self, entries: list[AccessEntry]) -> None:
        if not entries:
            return
        await self._pool.executemany(
            "INSERT INTO data_access_log (actor_id, subject_id, resource, resource_id, purpose) "
            "VALUES ($1, $2, $3, $4, $5)",
            [(uuid.UUID(e.actor_id), uuid.UUID(e.subject_id), e.resource,
              _uuid_or_none(e.resource_id), e.purpose) for e in entries],
        )

    async def list_by_subject(
        self, subject_id: str, *, limit: int = 100, before: datetime | None = None
    ) -> list[AccessRow]:
        sid = _uuid_or_none(subject_id)
        if sid is None:
            return []
        rows = await self._pool.fetch(
            "SELECT id, actor_id, subject_id, resource, resource_id, purpose, created_at "
            "FROM data_access_log WHERE subject_id = $1 "
            "AND ($2::timestamptz IS NULL OR created_at < $2) "
            "ORDER BY created_at DESC, id DESC LIMIT $3",
            sid, before, limit,
        )
        return [
            AccessRow(
                id=r["id"],
                actor_id=str(r["actor_id"]),
                subject_id=str(r["subject_id"]),
                resource=r["resource"],
                resource_id=str(r["resource_id"]) if r["resource_id"] else None,
                purpose=r["purpose"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
