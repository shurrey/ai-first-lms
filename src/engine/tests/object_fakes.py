from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InMemoryObjectDirectory:
    """ObjectDirectory over explicit submission -> course and bank -> course maps."""

    submissions: dict[str, str] = field(default_factory=dict)
    banks: dict[str, str] = field(default_factory=dict)

    async def submission_course(self, submission_id: str) -> str | None:
        return self.submissions.get(submission_id)

    async def question_bank_course(self, bank_id: str) -> str | None:
        return self.banks.get(bank_id)
