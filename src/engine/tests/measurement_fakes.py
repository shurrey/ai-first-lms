"""In-memory MeasurementStore with the same filtering and ordering as PgMeasurementStore."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.measurement import (
    ActionQuery,
    ActionRecord,
    DecisionRecord,
    LearnerRelease,
    LinkRecord,
    Program,
)


@dataclass
class InMemoryMeasurementStore:
    actions: list[ActionRecord] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    links: list[LinkRecord] = field(default_factory=list)
    criteria: dict[tuple[str, str], str] = field(default_factory=dict)
    titles: dict[tuple[str, str], str] = field(default_factory=dict)
    programs: dict[str, Program] = field(default_factory=dict)
    committed_grades: set[str] = field(default_factory=set)
    released_actions: set[str] = field(default_factory=set)

    def _latest(self, action_id: str) -> str | None:
        mine = sorted((d for d in self.decisions if d.ai_action_id == action_id),
                      key=lambda d: (d.decided_at, d.id))
        return mine[-1].decision if mine else None

    def _matches(self, a: ActionRecord, q: ActionQuery) -> bool:
        if q.course_ids is not None and a.course_node not in q.course_ids:
            return False
        if q.subject_ids is not None and a.subject_person not in q.subject_ids:
            return False
        if q.agent is not None and a.agent != q.agent:
            return False
        if q.action_type is not None and a.action_type != q.action_type:
            return False
        if q.decision is not None:
            latest = self._latest(a.id)
            if (latest or "none") != q.decision:
                return False
        if q.start is not None and a.created_at < q.start:
            return False
        if a.created_at >= q.end:
            return False
        return q.before is None or (a.created_at, a.id) < q.before

    async def find_actions(self, query: ActionQuery) -> list[ActionRecord]:
        found = sorted((a for a in self.actions if self._matches(a, query)),
                       key=lambda a: (a.created_at, a.id), reverse=True)
        return found[:query.limit] if query.limit is not None else found

    async def get_action(self, action_id: str) -> ActionRecord | None:
        return next((a for a in self.actions if a.id == action_id), None)

    async def decisions_for(self, action_ids: Iterable[str]
                            ) -> dict[str, list[DecisionRecord]]:
        wanted = set(action_ids)
        found: dict[str, list[DecisionRecord]] = {}
        for d in sorted(self.decisions, key=lambda d: (d.decided_at, d.id)):
            if d.ai_action_id in wanted:
                found.setdefault(d.ai_action_id, []).append(d)
        return found

    async def links_for(self, action_ids: Iterable[str]) -> dict[str, list[LinkRecord]]:
        wanted = set(action_ids)
        found: dict[str, list[LinkRecord]] = {}
        for link in sorted(self.links, key=lambda x: x.observed_at):
            if link.ai_action_id in wanted:
                found.setdefault(link.ai_action_id, []).append(link)
        return found

    async def criterion_ids(self, pairs: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], str]:
        return {p: self.criteria[p] for p in pairs if p in self.criteria}

    async def source_titles(self, refs: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], str]:
        return {r: self.titles[r] for r in refs if r in self.titles}

    async def program(self, program_id: str) -> Program | None:
        return self.programs.get(program_id)

    async def learner_release(self, actions: Iterable[ActionRecord]) -> LearnerRelease:
        actions = list(actions)
        return LearnerRelease(
            frozenset(a.target_id for a in actions if a.target_id in self.committed_grades),
            frozenset(a.id for a in actions if a.id in self.released_actions))
