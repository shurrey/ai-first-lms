"""In-memory FormativeStore and a recording MCP tool caller for formative-loop tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from engine.formative.store import (
    AssignmentRow,
    CriterionRow,
    DecisionRow,
    SubmissionQuery,
    SubmissionRow,
)

T0 = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
LEVELS = [{"score": 1, "label": "Beginning"}, {"score": 2, "label": "Developing"},
          {"score": 3, "label": "Proficient"}, {"score": 4, "label": "Exemplary"}]


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class InMemoryFormativeStore:
    submissions: dict[str, SubmissionRow] = field(default_factory=dict)
    assignments: dict[str, AssignmentRow] = field(default_factory=dict)
    rubrics: dict[str, list[CriterionRow]] = field(default_factory=dict)
    scores: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_rows: dict[str, list[DecisionRow]] = field(default_factory=dict)
    settings: dict[tuple[str, str], Any] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    practice: dict[tuple[str, str], str] = field(default_factory=dict)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[str, list[str]] = field(default_factory=dict)
    dismissed: dict[str, str] = field(default_factory=dict)

    # --- seeding helpers --------------------------------------------------------------

    def add_assignment(self, course_id: str, keys: Iterable[str] = ("thesis", "evidence"),
                       outcome_nodes: tuple[str, ...] = ()) -> AssignmentRow:
        rubric = new_id()
        self.rubrics[rubric] = [
            CriterionRow(submission_id="", criterion_id=new_id(), key=key,
                         description=f"{key} description", levels=list(LEVELS),
                         outcome_nodes=outcome_nodes)
            for key in keys]
        row = AssignmentRow(new_id(), "Essay 1", course_id, rubric)
        self.assignments[row.id] = row
        return row

    def criterion(self, assignment: AssignmentRow, key: str) -> CriterionRow:
        assert assignment.rubric_id is not None
        return next(c for c in self.rubrics[assignment.rubric_id] if c.key == key)

    def add_submission(self, assignment: AssignmentRow, person_id: str, *,
                       status: str = "draft", body: str = "An essay body.",
                       parent: SubmissionRow | None = None,
                       at: datetime | None = None) -> SubmissionRow:
        row = SubmissionRow(
            id=new_id(), person_id=person_id, assignment_id=assignment.id,
            course_id=assignment.course_id, version=parent.version + 1 if parent else 1,
            parent_id=parent.id if parent else None, status=status,
            submitted_at=at or T0 + timedelta(minutes=len(self.submissions)), body_md=body,
            rubric_id=assignment.rubric_id, assignment_title=assignment.title)
        self.submissions[row.id] = row
        return row

    def score(self, submission: SubmissionRow, key: str, ai_score: int, *,
              action: str | None = None, released: bool = False, next_step: str = "Next.",
              **extra: Any) -> str:
        """Saves feedback for one criterion as the server would; returns the action id."""
        assignment = self.assignments[submission.assignment_id]
        criterion = self.criterion(assignment, key)
        action = action or new_id()
        self.scores[(submission.id, criterion.criterion_id)] = {
            "ai_score": ai_score, "ai_rationale": f"{key} rationale",
            "ai_evidence_spans": [], "ai_action_id": action,
            "released_at": T0 if released else None, **extra}
        output = self.outputs.setdefault(action, {"submission_id": submission.id,
                                                  "criteria": []})
        output["criteria"].append({"criterion_id": criterion.criterion_id,
                                   "next_step": next_step})
        return action

    def decide(self, action: str, criterion_id: str, decision: str,
               diff: dict[str, Any] | None = None) -> None:
        rows = self.decision_rows.setdefault(action, [])
        rows.append(DecisionRow(new_id(), action, new_id(), decision,
                                {"criterion_id": criterion_id, **(diff or {})}, None,
                                T0 + timedelta(hours=len(rows) + 1)))

    # --- FormativeStore -----------------------------------------------------------------

    async def submission(self, submission_id: str) -> SubmissionRow | None:
        return self.submissions.get(submission_id)

    async def assignment(self, assignment_id: str) -> AssignmentRow | None:
        return self.assignments.get(assignment_id)

    async def list_submissions(self, query: SubmissionQuery) -> list[SubmissionRow]:
        revised = {s.parent_id for s in self.submissions.values() if s.parent_id}
        rows = [s for s in self.submissions.values()
                if (query.person_ids is None or s.person_id in query.person_ids)
                and (query.course_ids is None or s.course_id in query.course_ids)
                and (query.assignment_id is None or s.assignment_id == query.assignment_id)
                and (query.all_versions or s.id not in revised)]
        rows.sort(key=lambda s: (s.submitted_at, s.id), reverse=True)
        return rows[query.offset:query.offset + query.limit]

    async def versions(self, person_id: str, assignment_id: str) -> list[SubmissionRow]:
        return sorted((s for s in self.submissions.values()
                       if s.person_id == person_id and s.assignment_id == assignment_id),
                      key=lambda s: (s.version, s.submitted_at))

    async def criteria(self, submission_ids: Iterable[str]) -> dict[str, list[CriterionRow]]:
        out: dict[str, list[CriterionRow]] = {}
        for sid in submission_ids:
            sub = self.submissions.get(sid)
            if sub is None or sub.rubric_id is None:
                continue
            out[sid] = [replace(c, submission_id=sid,
                                **self.scores.get((sid, c.criterion_id), {}))
                        for c in self.rubrics.get(sub.rubric_id, [])]
        return out

    async def criterion_info(self, criterion_ids: Iterable[str]) -> dict[str, CriterionRow]:
        wanted = set(criterion_ids)
        return {c.criterion_id: c for rows in self.rubrics.values() for c in rows
                if c.criterion_id in wanted}

    async def action_outputs(self, action_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {a: self.outputs[a] for a in action_ids if a in self.outputs}

    async def decisions(self, action_ids: Iterable[str]) -> dict[str, list[DecisionRow]]:
        return {a: list(self.decision_rows[a]) for a in action_ids if a in self.decision_rows}

    async def annotate_action(self, action_id: str, *, model: str | None,
                              prompt_sha256: str | None, sources: list[dict[str, Any]],
                              output: dict[str, Any]) -> bool:
        self.annotations.append({"action_id": action_id, "model": model,
                                 "prompt_sha256": prompt_sha256, "sources": sources,
                                 "output": output})
        return True

    async def course_setting(self, course_id: str, key: str) -> tuple[bool, Any]:
        found = (course_id, key) in self.settings
        return found, self.settings.get((course_id, key))

    async def awaiting_release(self, course_ids: frozenset[str], offset: int, limit: int
                               ) -> list[str]:
        out = []
        for sub in sorted(self.submissions.values(), key=lambda s: s.submitted_at):
            if sub.status != "draft" or sub.course_id not in course_ids:
                continue
            for (sid, cid), score in self.scores.items():
                rejected = any(d.decision == "rejected" and d.diff
                               and d.diff.get("criterion_id") == cid
                               for d in self.decision_rows.get(score["ai_action_id"], []))
                if sid == sub.id and score.get("released_at") is None and not rejected:
                    out.append(sub.id)
                    break
        return out[offset:offset + limit]

    async def display_names(self, person_ids: Iterable[str]) -> dict[str, str]:
        return {p: self.names[p] for p in person_ids if p in self.names}

    async def record_feedback_failure(self, submission: SubmissionRow, reason: str) -> str:
        action = new_id()
        self.failures.setdefault(submission.id, []).append(action)
        self.outputs[action] = {"submission_id": submission.id, "failed": True,
                                "reason": reason}
        return action

    async def feedback_failures(self, submission_ids: Iterable[str]) -> dict[str, list[str]]:
        out = {}
        for sid in submission_ids:
            open_ = [a for a in self.failures.get(sid, []) if a not in self.dismissed]
            if open_:
                out[sid] = open_
        return out

    async def dismiss_failures(self, action_ids: Iterable[str], decided_by: str) -> None:
        for action in action_ids:
            self.dismissed[action] = decided_by

    async def practice_sets(self, person_id: str, criterion_ids: Iterable[str]
                            ) -> dict[str, str]:
        return {c: self.practice[(person_id, c)] for c in criterion_ids
                if (person_id, c) in self.practice}


Reply = dict[str, Any] | Callable[[dict[str, Any]], Any]


class RecordingTools:
    """An MCP tool caller returning canned replies (a dict, or a function of the args)."""

    def __init__(self, replies: dict[str, Reply] | None = None) -> None:
        self.replies: dict[str, Reply] = dict(replies or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> Any:
        self.calls.append((tool, dict(args)))
        reply = self.replies.get(tool, {"ok": True})
        return reply(args) if callable(reply) else reply

    def calls_to(self, tool: str) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == tool]
