from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from engine.provenance import (
    AiActionRow,
    HumanDecisionRow,
    StoredAction,
    StoredDecision,
    as_uuid,
)

_EPOCH = datetime(2026, 10, 2, tzinfo=UTC)


@dataclass
class InMemoryProvenanceStore:
    """ProvenanceStore over lists. Timestamps advance one second per write so ordering is
    deterministic; `fail` makes every write raise."""

    actions: list[AiActionRow] = field(default_factory=list)
    decided: list[HumanDecisionRow] = field(default_factory=list)
    pending: dict[tuple[str, str], str] = field(default_factory=dict)
    fail: bool = False
    _times: dict[str, datetime] = field(default_factory=dict)

    def _stamp(self, row_id: str) -> None:
        self._times[row_id] = _EPOCH + timedelta(seconds=len(self._times))

    async def record_action(self, row: AiActionRow) -> bool:
        if self.fail:
            raise ConnectionError("database is down")
        if any(a.id == row.id for a in self.actions):
            return False
        self.actions.append(row)
        self._stamp(row.id)
        return True

    async def record_decision(self, row: HumanDecisionRow) -> bool:
        if self.fail:
            raise ConnectionError("database is down")
        if any(d.id == row.id for d in self.decided):
            return False
        self.decided.append(row)
        self._stamp(row.id)
        return True

    def _stored(self, row: AiActionRow) -> StoredAction:
        return StoredAction(row.id, row.agent, row.action_type, as_uuid(row.subject_person),
                            as_uuid(row.course_node), row.target_type, as_uuid(row.target_id),
                            row.output, self._times[row.id])

    async def get_action(self, action_id: str) -> StoredAction | None:
        return next((self._stored(a) for a in self.actions if a.id == action_id), None)

    async def find_actions(self, action_type: str, *, target_type: str | None = None,
                           target_id: str | None = None, output_key: str | None = None,
                           output_value: str | None = None) -> list[StoredAction]:
        return [self._stored(a) for a in self.actions
                if a.action_type == action_type
                and (target_type is None or a.target_type == target_type)
                and (target_id is None or as_uuid(a.target_id) == as_uuid(target_id))
                and (output_key is None or a.output.get(output_key) == output_value)]

    async def decisions(self, action_id: str) -> list[StoredDecision]:
        return [StoredDecision(d.id, d.ai_action_id, d.decided_by, d.decision, d.diff,
                               d.reason, self._times[d.id])
                for d in self.decided if d.ai_action_id == action_id]

    async def pending_credential_id(self, person_id: str, microcredential_id: str
                                    ) -> str | None:
        return self.pending.get((person_id, microcredential_id))

    def of_type(self, action_type: str) -> list[AiActionRow]:
        return [a for a in self.actions if a.action_type == action_type]

    def decisions_on(self, action_id: str) -> list[HumanDecisionRow]:
        return [d for d in self.decided if d.ai_action_id == action_id]
