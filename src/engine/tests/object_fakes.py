from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from engine.auth.access_log import AccessEntry, AccessFilter, AccessRow


@dataclass
class InMemoryObjectDirectory:
    """ObjectDirectory over explicit id -> course maps."""

    submissions: dict[str, str] = field(default_factory=dict)
    banks: dict[str, str] = field(default_factory=dict)
    criteria: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, str] = field(default_factory=dict)

    async def submission_course(self, submission_id: str) -> str | None:
        return self.submissions.get(submission_id)

    async def question_bank_course(self, bank_id: str) -> str | None:
        return self.banks.get(bank_id)

    async def criterion_course(self, criterion_id: str) -> str | None:
        return self.criteria.get(criterion_id)

    async def node_course(self, node_id: str) -> str | None:
        return self.nodes.get(node_id)


@dataclass
class InMemoryAccessLog:
    """AccessLog over a list; `fail` makes every write raise."""

    entries: list[AccessEntry] = field(default_factory=list)
    fail: bool = False
    names: dict[str, str] = field(default_factory=dict)  # actor id -> display name

    async def record(self, entry: AccessEntry) -> None:
        if self.fail:
            raise ConnectionError("database is down")
        self.entries.append(entry)

    async def record_many(self, entries: list[AccessEntry]) -> None:
        if self.fail:
            raise ConnectionError("database is down")
        self.entries.extend(entries)

    async def list_by_subject(
        self, subject_id: str, *, limit: int = 100, before: datetime | None = None,
        where: AccessFilter | None = None,
    ) -> list[AccessRow]:
        """`before` is ignored; rows carry their list position as id and share one timestamp,
        so `where.before` pages by id and `where.start` / `end` match all or nothing."""
        f = where or AccessFilter()
        now = datetime.now(UTC)
        rows = [AccessRow(i, e.actor_id, e.subject_id, e.resource, e.resource_id, e.purpose,
                          now, self.names.get(e.actor_id))
                for i, e in enumerate(self.entries) if e.subject_id == subject_id
                and f.resource in (None, e.resource)
                and (f.before is None or i < f.before[1])
                and (f.start is None or now >= f.start) and (f.end is None or now < f.end)]
        return rows[::-1][:limit]
