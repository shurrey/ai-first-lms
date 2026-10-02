from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from engine.auth.access_log import AccessEntry, AccessRow


@dataclass
class InMemoryObjectDirectory:
    """ObjectDirectory over explicit submission -> course and bank -> course maps."""

    submissions: dict[str, str] = field(default_factory=dict)
    banks: dict[str, str] = field(default_factory=dict)

    async def submission_course(self, submission_id: str) -> str | None:
        return self.submissions.get(submission_id)

    async def question_bank_course(self, bank_id: str) -> str | None:
        return self.banks.get(bank_id)


@dataclass
class InMemoryAccessLog:
    """AccessLog over a list; `fail` makes every write raise."""

    entries: list[AccessEntry] = field(default_factory=list)
    fail: bool = False

    async def record(self, entry: AccessEntry) -> None:
        if self.fail:
            raise ConnectionError("database is down")
        self.entries.append(entry)

    async def record_many(self, entries: list[AccessEntry]) -> None:
        if self.fail:
            raise ConnectionError("database is down")
        self.entries.extend(entries)

    async def list_by_subject(
        self, subject_id: str, *, limit: int = 100, before: datetime | None = None
    ) -> list[AccessRow]:
        """`before` is ignored; rows carry their list position as id."""
        rows = [AccessRow(i, e.actor_id, e.subject_id, e.resource, e.resource_id, e.purpose,
                          datetime.now(UTC))
                for i, e in enumerate(self.entries) if e.subject_id == subject_id]
        return rows[::-1][:limit]
