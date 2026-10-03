"""Reads behind the formative-loop endpoints, and the engine's additions to ai_actions rows.

Submissions, rubric criteria and criterion scores are read directly, like the measurement
store; every change to them goes through the assessments MCP tools, which also write the
criterion_feedback and practice_item ai_actions rows. Ids cross this boundary as UUID text.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import asyncpg

from engine.provenance import as_uuid, canonical_json, source

# Output key marking a criterion_feedback action as a feedback run that saved nothing.
FAILED = "failed"


@dataclass(frozen=True)
class SubmissionRow:
    id: str
    person_id: str
    assignment_id: str
    course_id: str | None
    version: int
    parent_id: str | None
    status: str  # draft | final
    submitted_at: datetime
    body_md: str | None = None
    attachments: list[Any] = field(default_factory=list)
    rubric_id: str | None = None
    assignment_title: str | None = None


@dataclass(frozen=True)
class AssignmentRow:
    id: str
    title: str
    course_id: str | None
    rubric_id: str | None


@dataclass(frozen=True)
class CriterionRow:
    """A rubric criterion of the submission's assignment, with its score row if any."""

    submission_id: str
    criterion_id: str
    key: str
    description: str
    levels: list[dict[str, Any]] = field(default_factory=list)
    outcome_nodes: tuple[str, ...] = ()
    ai_score: int | None = None
    ai_rationale: str | None = None
    ai_evidence_spans: list[dict[str, Any]] = field(default_factory=list)
    final_score: int | None = None
    ai_action_id: str | None = None
    released_at: datetime | None = None


@dataclass(frozen=True)
class DecisionRow:
    id: str
    ai_action_id: str
    decided_by: str
    decision: str
    diff: dict[str, Any] | None
    reason: str | None
    decided_at: datetime


@dataclass(frozen=True)
class SubmissionQuery:
    """`None` means unrestricted; an empty set matches nothing."""

    person_ids: frozenset[str] | None = None
    course_ids: frozenset[str] | None = None
    assignment_id: str | None = None
    all_versions: bool = False
    offset: int = 0
    limit: int = 50


class FormativeStore(Protocol):
    async def submission(self, submission_id: str) -> SubmissionRow | None: ...

    async def assignment(self, assignment_id: str) -> AssignmentRow | None: ...

    async def list_submissions(self, query: SubmissionQuery) -> list[SubmissionRow]:
        """Newest first; without `all_versions`, only versions nothing revises."""
        ...

    async def versions(self, person_id: str, assignment_id: str) -> list[SubmissionRow]:
        """Every version this person submitted for the assignment, oldest first."""
        ...

    async def criteria(self, submission_ids: Iterable[str]) -> dict[str, list[CriterionRow]]:
        """Per submission, its assignment's rubric criteria plus any other scored criterion,
        ordered by key."""
        ...

    async def criterion_info(self, criterion_ids: Iterable[str]) -> dict[str, CriterionRow]:
        """Rubric criteria by id, unscored (`submission_id` is "")."""
        ...

    async def action_outputs(self, action_ids: Iterable[str]) -> dict[str, dict[str, Any]]: ...

    async def decisions(self, action_ids: Iterable[str]) -> dict[str, list[DecisionRow]]:
        """Per action, oldest first."""
        ...

    async def annotate_action(self, action_id: str, *, model: str | None,
                              prompt_sha256: str | None, sources: list[dict[str, Any]],
                              output: dict[str, Any]) -> bool:
        """Adds what only the engine knows to a server-written ai_actions row: the model and
        prompt hash (kept when already set), extra sources (merged, deduplicated) and extra
        output keys. False when there is no such row."""
        ...

    async def course_setting(self, course_id: str, key: str) -> tuple[bool, Any]:
        """(found, value) of the course's current policy_settings row for `key`."""
        ...

    async def awaiting_release(self, course_ids: frozenset[str], offset: int, limit: int
                               ) -> list[str]:
        """Draft submissions in these courses with recorded, unreleased, unrejected
        criterion feedback; oldest first."""
        ...

    async def display_names(self, person_ids: Iterable[str]) -> dict[str, str]: ...

    async def record_feedback_failure(self, submission: SubmissionRow, reason: str) -> str:
        """Writes a criterion_feedback ai_actions row with output `failed: true` for a
        feedback run that saved nothing; returns its id."""
        ...

    async def feedback_failures(self, submission_ids: Iterable[str]) -> dict[str, list[str]]:
        """Per submission, its failed-run action ids that no one has dismissed."""
        ...

    async def dismiss_failures(self, action_ids: Iterable[str], decided_by: str) -> None:
        """Records a `dismissed` human decision on each failed-run action."""
        ...

    async def practice_sets(self, person_id: str, criterion_ids: Iterable[str]
                            ) -> dict[str, str]:
        """Latest practice_item action id per criterion for this learner, leaving out
        sets the learner dismissed."""
        ...


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _uuids(values: Iterable[str | None]) -> list[str]:
    return sorted({u for u in (as_uuid(v) for v in values) if u})


# The three submission reads share one column list; keep them in step with `_submission`.
_ONE_SUBMISSION = """
    SELECT s.id, s.person_id, s.assignment_node, s.version, s.parent_id, s.status, s.body_md,
           s.attachments, s.submitted_at, a.title AS assignment_title,
           a.metadata->>'rubric_id' AS rubric_id,
           COALESCE(s.course_node::text, a.metadata->>'course_id') AS course_id
    FROM submissions s JOIN nodes a ON a.id = s.assignment_node
    WHERE s.id = $1::uuid
"""
_LIST_SUBMISSIONS = """
    SELECT s.id, s.person_id, s.assignment_node, s.version, s.parent_id, s.status, s.body_md,
           s.attachments, s.submitted_at, a.title AS assignment_title,
           a.metadata->>'rubric_id' AS rubric_id,
           COALESCE(s.course_node::text, a.metadata->>'course_id') AS course_id
    FROM submissions s JOIN nodes a ON a.id = s.assignment_node
    WHERE ($1::uuid[] IS NULL OR s.person_id = ANY($1::uuid[]))
      AND ($2::text[] IS NULL
           OR COALESCE(s.course_node::text, a.metadata->>'course_id') = ANY($2::text[]))
      AND ($3::uuid IS NULL OR s.assignment_node = $3::uuid)
      AND ($4 OR NOT EXISTS (SELECT 1 FROM submissions c WHERE c.parent_id = s.id))
    ORDER BY s.submitted_at DESC, s.id DESC
    OFFSET $5 LIMIT $6
"""
_VERSIONS = """
    SELECT s.id, s.person_id, s.assignment_node, s.version, s.parent_id, s.status, s.body_md,
           s.attachments, s.submitted_at, a.title AS assignment_title,
           a.metadata->>'rubric_id' AS rubric_id,
           COALESCE(s.course_node::text, a.metadata->>'course_id') AS course_id
    FROM submissions s JOIN nodes a ON a.id = s.assignment_node
    WHERE s.person_id = $1::uuid AND s.assignment_node = $2::uuid
    ORDER BY s.version, s.submitted_at, s.id
"""


def _submission(row: asyncpg.Record) -> SubmissionRow:
    attachments = _json(row["attachments"])
    return SubmissionRow(
        id=str(row["id"]), person_id=str(row["person_id"]),
        assignment_id=str(row["assignment_node"]), course_id=as_uuid(row["course_id"]),
        version=row["version"], parent_id=_str(row["parent_id"]), status=row["status"],
        submitted_at=row["submitted_at"], body_md=row["body_md"],
        attachments=attachments if isinstance(attachments, list) else [],
        rubric_id=as_uuid(row["rubric_id"]), assignment_title=row["assignment_title"],
    )


class PgFormativeStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def submission(self, submission_id: str) -> SubmissionRow | None:
        sid = as_uuid(submission_id)
        if sid is None:
            return None
        row = await self._pool.fetchrow(_ONE_SUBMISSION, sid)
        return _submission(row) if row else None

    async def assignment(self, assignment_id: str) -> AssignmentRow | None:
        aid = as_uuid(assignment_id)
        if aid is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT id, title, metadata->>'course_id' AS course_id,"
            " metadata->>'rubric_id' AS rubric_id FROM nodes"
            " WHERE id = $1::uuid AND kind = 'assessment_item'", aid)
        if row is None:
            return None
        return AssignmentRow(str(row["id"]), row["title"], as_uuid(row["course_id"]),
                             as_uuid(row["rubric_id"]))

    async def list_submissions(self, query: SubmissionQuery) -> list[SubmissionRow]:
        rows = await self._pool.fetch(
            _LIST_SUBMISSIONS,
            _uuids(query.person_ids) if query.person_ids is not None else None,
            _uuids(query.course_ids) if query.course_ids is not None else None,
            as_uuid(query.assignment_id) if query.assignment_id else None,
            query.all_versions, query.offset, query.limit)
        return [_submission(r) for r in rows]

    async def versions(self, person_id: str, assignment_id: str) -> list[SubmissionRow]:
        pid, aid = as_uuid(person_id), as_uuid(assignment_id)
        if pid is None or aid is None:
            return []
        rows = await self._pool.fetch(_VERSIONS, pid, aid)
        return [_submission(r) for r in rows]

    async def criteria(self, submission_ids: Iterable[str]) -> dict[str, list[CriterionRow]]:
        ids = _uuids(submission_ids)
        if not ids:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT s.id AS submission_id, rc.id AS criterion_id, rc.key, rc.description,
                   rc.levels, rc.outcome_nodes, cs.ai_score, cs.ai_rationale,
                   cs.ai_evidence_spans, cs.final_score, cs.ai_action_id, cs.released_at
            FROM submissions s
            JOIN nodes a ON a.id = s.assignment_node
            JOIN rubric_criteria rc
              ON rc.rubric_id::text = a.metadata->>'rubric_id'
              OR EXISTS (SELECT 1 FROM criterion_scores x
                         WHERE x.submission_id = s.id AND x.criterion_id = rc.id)
            LEFT JOIN criterion_scores cs
              ON cs.submission_id = s.id AND cs.criterion_id = rc.id
            WHERE s.id = ANY($1::uuid[])
            ORDER BY s.id, rc.key, rc.id
            """, ids)
        out: dict[str, list[CriterionRow]] = {}
        for r in rows:
            levels = _json(r["levels"])
            spans = _json(r["ai_evidence_spans"])
            out.setdefault(str(r["submission_id"]), []).append(CriterionRow(
                submission_id=str(r["submission_id"]), criterion_id=str(r["criterion_id"]),
                key=r["key"], description=r["description"],
                levels=levels if isinstance(levels, list) else [],
                outcome_nodes=tuple(str(n) for n in r["outcome_nodes"] or ()),
                ai_score=r["ai_score"], ai_rationale=r["ai_rationale"],
                ai_evidence_spans=spans if isinstance(spans, list) else [],
                final_score=r["final_score"], ai_action_id=_str(r["ai_action_id"]),
                released_at=r["released_at"],
            ))
        return out

    async def criterion_info(self, criterion_ids: Iterable[str]) -> dict[str, CriterionRow]:
        ids = _uuids(criterion_ids)
        if not ids:
            return {}
        rows = await self._pool.fetch(
            "SELECT id, key, description, levels, outcome_nodes FROM rubric_criteria"
            " WHERE id = ANY($1::uuid[])", ids)
        out = {}
        for r in rows:
            levels = _json(r["levels"])
            out[str(r["id"])] = CriterionRow(
                submission_id="", criterion_id=str(r["id"]), key=r["key"],
                description=r["description"],
                levels=levels if isinstance(levels, list) else [],
                outcome_nodes=tuple(str(n) for n in r["outcome_nodes"] or ()))
        return out

    async def action_outputs(self, action_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = _uuids(action_ids)
        if not ids:
            return {}
        rows = await self._pool.fetch(
            "SELECT id, output FROM ai_actions WHERE id = ANY($1::uuid[])", ids)
        return {str(r["id"]): _json(r["output"]) or {} for r in rows}

    async def decisions(self, action_ids: Iterable[str]) -> dict[str, list[DecisionRow]]:
        ids = _uuids(action_ids)
        if not ids:
            return {}
        rows = await self._pool.fetch(
            "SELECT id, ai_action_id, decided_by, decision, diff, reason, decided_at"
            " FROM human_decisions WHERE ai_action_id = ANY($1::uuid[])"
            " ORDER BY decided_at, id", ids)
        out: dict[str, list[DecisionRow]] = {}
        for r in rows:
            diff = _json(r["diff"])
            out.setdefault(str(r["ai_action_id"]), []).append(DecisionRow(
                str(r["id"]), str(r["ai_action_id"]), str(r["decided_by"]), r["decision"],
                diff if isinstance(diff, dict) else None, r["reason"], r["decided_at"]))
        return out

    async def annotate_action(self, action_id: str, *, model: str | None,
                              prompt_sha256: str | None, sources: list[dict[str, Any]],
                              output: dict[str, Any]) -> bool:
        aid = as_uuid(action_id)
        if aid is None:
            return False
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT sources FROM ai_actions WHERE id = $1::uuid FOR UPDATE", aid)
            if row is None:
                return False
            current = _json(row["sources"])
            merged: dict[tuple[str, str], dict[str, Any]] = {}
            for item in [*(current if isinstance(current, list) else []), *sources]:
                if isinstance(item, dict) and item.get("type") and item.get("id"):
                    merged.setdefault((str(item["type"]), str(item["id"])), item)
            await conn.execute(
                "UPDATE ai_actions SET model = COALESCE(model, $2),"
                " prompt_sha256 = COALESCE(prompt_sha256, $3), sources = $4::jsonb,"
                " output = output || $5::jsonb WHERE id = $1::uuid",
                aid, model, prompt_sha256, canonical_json(list(merged.values())),
                canonical_json(output))
        return True

    async def course_setting(self, course_id: str, key: str) -> tuple[bool, Any]:
        cid = as_uuid(course_id)
        if cid is None:
            return False, None
        row = await self._pool.fetchrow(
            "SELECT value FROM policy_settings WHERE key = $1 AND scope_type = 'course'"
            " AND scope_id = $2::uuid AND superseded_at IS NULL AND effective_from <= now()"
            " ORDER BY version DESC LIMIT 1", key, cid)
        return (True, _json(row["value"])) if row else (False, None)

    async def awaiting_release(self, course_ids: frozenset[str], offset: int, limit: int
                               ) -> list[str]:
        courses = _uuids(course_ids)
        if not courses:
            return []
        rows = await self._pool.fetch(
            """
            SELECT s.id FROM submissions s JOIN nodes a ON a.id = s.assignment_node
            WHERE s.status = 'draft'
              AND COALESCE(s.course_node::text, a.metadata->>'course_id') = ANY($1::text[])
              AND EXISTS (
                SELECT 1 FROM criterion_scores cs
                WHERE cs.submission_id = s.id AND cs.ai_score IS NOT NULL
                  AND cs.ai_action_id IS NOT NULL AND cs.released_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM human_decisions d
                                  WHERE d.ai_action_id = cs.ai_action_id
                                    AND d.decision = 'rejected'))
            ORDER BY s.submitted_at, s.id
            OFFSET $2 LIMIT $3
            """, courses, offset, limit)
        return [str(r["id"]) for r in rows]

    async def display_names(self, person_ids: Iterable[str]) -> dict[str, str]:
        ids = _uuids(person_ids)
        if not ids:
            return {}
        rows = await self._pool.fetch(
            "SELECT id, display_name FROM persons WHERE id = ANY($1::uuid[])", ids)
        return {str(r["id"]): r["display_name"] for r in rows}

    async def record_feedback_failure(self, submission: SubmissionRow, reason: str) -> str:
        action_id = str(uuid.uuid4())
        await self._pool.execute(
            """
            INSERT INTO ai_actions (id, agent, action_type, subject_person, course_node,
                                    target_type, target_id, sources, output)
            VALUES ($1::uuid, 'feedback', 'criterion_feedback', $2::uuid,
                    (SELECT id FROM nodes WHERE id = $3::uuid), 'submissions', $4::uuid,
                    $5::jsonb, $6::jsonb)
            """, action_id, submission.person_id, as_uuid(submission.course_id),
            submission.id,
            canonical_json([source("submission", submission.id, submission.version)]),
            canonical_json({"submission_id": submission.id, FAILED: True, "reason": reason}))
        return action_id

    async def feedback_failures(self, submission_ids: Iterable[str]) -> dict[str, list[str]]:
        ids = _uuids(submission_ids)
        if not ids:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT a.target_id, a.id FROM ai_actions a
            WHERE a.action_type = 'criterion_feedback' AND a.target_type = 'submissions'
              AND a.target_id = ANY($1::uuid[]) AND a.output @> '{"failed": true}'::jsonb
              AND NOT EXISTS (SELECT 1 FROM human_decisions d
                              WHERE d.ai_action_id = a.id AND d.decision = 'dismissed')
            ORDER BY a.created_at, a.id
            """, ids)
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(str(r["target_id"]), []).append(str(r["id"]))
        return out

    async def dismiss_failures(self, action_ids: Iterable[str], decided_by: str) -> None:
        ids = _uuids(action_ids)
        if not ids:
            return
        await self._pool.execute(
            "INSERT INTO human_decisions (ai_action_id, decided_by, decision)"
            " SELECT unnest($1::uuid[]), $2::uuid, 'dismissed'", ids, as_uuid(decided_by))

    async def practice_sets(self, person_id: str, criterion_ids: Iterable[str]
                            ) -> dict[str, str]:
        pid, criteria = as_uuid(person_id), _uuids(criterion_ids)
        if pid is None or not criteria:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT ON (a.output->>'criterion_id') a.output->>'criterion_id' AS cid, a.id
            FROM ai_actions a
            WHERE a.action_type = 'practice_item' AND a.subject_person = $1::uuid
              AND a.output->>'criterion_id' = ANY($2::text[])
              AND NOT EXISTS (SELECT 1 FROM human_decisions d
                              WHERE d.ai_action_id = a.id AND d.decision = 'dismissed')
            ORDER BY a.output->>'criterion_id', a.created_at DESC, a.id DESC
            """, pid, criteria)
        return {r["cid"]: str(r["id"]) for r in rows}
