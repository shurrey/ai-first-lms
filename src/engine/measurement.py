"""Reads behind the AI Review views and the provenance log (spec.md §6.5).

`MeasurementStore` reads `ai_actions`, `human_decisions` and `outcome_links`; `summarize`
turns those rows into the MeasurementSummary numbers. An action's decision is its latest
`human_decisions` row (by decided_at, then id); an action without one is undecided.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

import asyncpg

from engine.formative.policy import show_scores_on_drafts
from engine.formative.store import FAILED, PgFormativeStore
from engine.guardrails.pii import pseudonym, scan_and_redact_result
from engine.provenance import as_uuid

ACCEPTED, EDITED, REJECTED = "accepted", "edited", "rejected"
OTHER_DECISIONS = frozenset({"overridden", "dismissed", "disputed", "snoozed"})
_NO_FINAL_SCORES = frozenset({"dismissed", "disputed", "snoozed"})
# Action types whose decisions are on instructor-facing feedback drafts (§6.5).
FEEDBACK_TYPES = frozenset({"grade_draft", "criterion_feedback"})
# Generated items only their subject learner sees (§12.5); others get PracticeCounts.
PRIVATE_TYPES = frozenset({"practice_item"})
PRACTICE = "practice_item"
# Evidence visibilities a learner-view outcome link may cite.
SHARED_EVIDENCE = frozenset({"course", "program"})
MOST_EDITED_LIMIT = 10
TITLED_SOURCES = frozenset({"node", "content_item", "rubric"})

# Synthetic criterion ids (see `criterion_uuid`) and pseudonymous person ids live here.
_NAMESPACE = uuid.UUID("0b8f3c1e-6a2d-4e57-9a41-2f7d5c3e8b19")


@dataclass(frozen=True)
class ActionRecord:
    id: str
    agent: str
    action_type: str
    output: dict[str, Any]
    created_at: datetime
    session_id: str | None = None
    turn_id: str | None = None
    subject_person: str | None = None
    course_node: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    sources: tuple[dict[str, Any], ...] = ()
    policies: tuple[dict[str, Any], ...] = ()
    model: str | None = None
    prompt_sha256: str | None = None


@dataclass(frozen=True)
class DecisionRecord:
    id: str
    ai_action_id: str
    decided_by: str
    decision: str
    decided_at: datetime
    decided_by_name: str | None = None
    diff: dict[str, Any] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class LinkRecord:
    ai_action_id: str
    observed_at: datetime
    evidence_id: str | None = None
    attestation_id: str | None = None
    delta: dict[str, Any] | None = None


@dataclass(frozen=True)
class Program:
    id: str
    title: str
    lead_ids: frozenset[str]
    course_ids: frozenset[str]


@dataclass(frozen=True)
class ReleasedCriterion:
    """A released `criterion_scores` row: the feedback as the learner was given it."""

    ai_score: int | None
    ai_rationale: str | None
    evidence_spans: list[Any]
    hide_score: bool = False  # draft in a course with feedback.show_scores_on_drafts=false


@dataclass(frozen=True)
class LearnerRelease:
    """Which feedback has reached its learner: committed grades (`grades.id`) and released
    criterion feedback (ai_action ids with a `criterion_scores.released_at`, which the
    release flow sets under either `feedback.release_mode`). `released_criteria` holds the
    released rows per action and criterion id."""

    committed_grades: frozenset[str] = frozenset()
    released_actions: frozenset[str] = frozenset()
    released_criteria: dict[str, dict[str, ReleasedCriterion]] = field(default_factory=dict)


@dataclass(frozen=True)
class LinkTargets:
    """The observed ("after") sides of outcome links that their learner can see, each mapped
    to the criterion score the learner sees there now: evidence ids (None when the evidence
    scores no criterion), and (submission_id, criterion_id) criterion scores."""

    evidence: Mapping[str, float | None] = field(default_factory=dict)
    scores: Mapping[tuple[str, str], float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionQuery:
    """`None` sets mean unrestricted; an empty set matches nothing. `end` is exclusive.
    `before` is the (created_at, id) of the last row of the previous page.
    `draft_feedback_courses` limits criterion_feedback on draft submissions to those courses."""

    end: datetime
    start: datetime | None = None
    course_ids: frozenset[str] | None = None
    subject_ids: frozenset[str] | None = None
    agent: str | None = None
    action_type: str | None = None
    decision: str | None = None  # latest decision value, or "none"
    limit: int | None = None
    before: tuple[datetime, str] | None = None
    ids: frozenset[str] | None = None
    exclude_types: frozenset[str] = frozenset()
    draft_feedback_courses: frozenset[str] | None = None


class MeasurementStore(Protocol):
    async def find_actions(self, query: ActionQuery) -> list[ActionRecord]:
        """Newest first."""
        ...

    async def get_action(self, action_id: str) -> ActionRecord | None: ...

    async def decisions_for(self, action_ids: Iterable[str]
                            ) -> dict[str, list[DecisionRecord]]:
        """Per action, oldest first; actions without decisions are absent."""
        ...

    async def links_for(self, action_ids: Iterable[str]) -> dict[str, list[LinkRecord]]: ...

    async def criterion_ids(self, pairs: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], str]:
        """`rubric_criteria.id` by (rubric_id, key.lower()), for the pairs that exist."""
        ...

    async def source_titles(self, refs: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], str]:
        """Titles by (source type, id) for node, content_item and rubric sources."""
        ...

    async def program(self, program_id: str) -> Program | None: ...

    async def learner_release(self, actions: Iterable[ActionRecord]) -> LearnerRelease: ...

    async def learner_link_targets(self, links: Iterable[LinkRecord]) -> LinkTargets:
        """Which of these links' observations their learner can see (see `learner_links`)."""
        ...


# --- Postgres ------------------------------------------------------------------------------


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _uuids(values: Iterable[str]) -> list[str]:
    return [u for u in (as_uuid(v) for v in values) if u is not None]


# Literal per kind so no SQL text is ever assembled at run time (CI's ruff S608 gate).
_TITLE_QUERIES = {
    "node": "SELECT id, title FROM nodes WHERE id = ANY($1::uuid[])",
    "content_item": "SELECT id, title FROM content_items WHERE id = ANY($1::uuid[])",
    "rubric": "SELECT id, title FROM rubrics WHERE id = ANY($1::uuid[])",
}


def _action(row: asyncpg.Record) -> ActionRecord:
    sources, policies = _json(row["sources"]), _json(row["policies"])
    return ActionRecord(
        id=str(row["id"]), agent=row["agent"], action_type=row["action_type"],
        output=_json(row["output"]) or {}, created_at=row["created_at"],
        session_id=_str(row["session_id"]), turn_id=_str(row["turn_id"]),
        subject_person=_str(row["subject_person"]), course_node=_str(row["course_node"]),
        target_type=row["target_type"], target_id=_str(row["target_id"]),
        sources=tuple(s for s in sources or [] if isinstance(s, dict)),
        policies=tuple(p for p in policies or [] if isinstance(p, dict)),
        model=row["model"], prompt_sha256=row["prompt_sha256"],
    )


class PgMeasurementStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def find_actions(self, query: ActionQuery) -> list[ActionRecord]:
        courses = None if query.course_ids is None else _uuids(query.course_ids)
        subjects = None if query.subject_ids is None else _uuids(query.subject_ids)
        before_at, before_id = query.before if query.before else (None, None)
        rows = await self._pool.fetch(
            """
            SELECT a.id, a.session_id, a.turn_id, a.agent, a.action_type, a.subject_person,
                   a.course_node, a.target_type, a.target_id, a.sources, a.policies, a.model,
                   a.prompt_sha256, a.output, a.created_at
            FROM ai_actions a
            LEFT JOIN LATERAL (
                SELECT d.decision FROM human_decisions d WHERE d.ai_action_id = a.id
                ORDER BY d.decided_at DESC, d.id DESC LIMIT 1) latest ON true
            WHERE ($1::uuid[] IS NULL OR a.course_node = ANY($1::uuid[]))
              AND ($2::uuid[] IS NULL OR a.subject_person = ANY($2::uuid[]))
              AND ($3::text IS NULL OR a.agent = $3)
              AND ($4::text IS NULL OR a.action_type = $4)
              AND ($5::text IS NULL OR latest.decision = $5
                   OR ($5 = 'none' AND latest.decision IS NULL))
              AND ($6::timestamptz IS NULL OR a.created_at >= $6)
              AND a.created_at < $7
              AND ($8::timestamptz IS NULL OR (a.created_at, a.id) < ($8, $9::uuid))
              AND ($11::uuid[] IS NULL OR a.id = ANY($11::uuid[]))
              AND NOT (a.action_type = ANY($12::text[]))
              AND ($13::uuid[] IS NULL OR a.action_type <> 'criterion_feedback'
                   OR a.course_node = ANY($13::uuid[])
                   OR NOT EXISTS (SELECT 1 FROM submissions s
                                  WHERE a.target_type = 'submissions' AND s.id = a.target_id
                                    AND s.status = 'draft'))
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT $10
            """,
            courses, subjects, query.agent, query.action_type, query.decision, query.start,
            query.end, before_at, as_uuid(before_id) if before_id else None, query.limit,
            None if query.ids is None else _uuids(query.ids), sorted(query.exclude_types),
            None if query.draft_feedback_courses is None
            else _uuids(query.draft_feedback_courses),
        )
        return [_action(r) for r in rows]

    async def get_action(self, action_id: str) -> ActionRecord | None:
        aid = as_uuid(action_id)
        if aid is None:
            return None
        row = await self._pool.fetchrow(
            """
            SELECT a.id, a.session_id, a.turn_id, a.agent, a.action_type, a.subject_person,
                   a.course_node, a.target_type, a.target_id, a.sources, a.policies, a.model,
                   a.prompt_sha256, a.output, a.created_at
            FROM ai_actions a WHERE a.id = $1::uuid
            """, aid)
        return _action(row) if row else None

    async def decisions_for(self, action_ids: Iterable[str]
                            ) -> dict[str, list[DecisionRecord]]:
        rows = await self._pool.fetch(
            """
            SELECT d.id, d.ai_action_id, d.decided_by, p.display_name, d.decision, d.diff,
                   d.reason, d.decided_at
            FROM human_decisions d LEFT JOIN persons p ON p.id = d.decided_by
            WHERE d.ai_action_id = ANY($1::uuid[])
            ORDER BY d.decided_at, d.id
            """, _uuids(action_ids))
        found: dict[str, list[DecisionRecord]] = {}
        for r in rows:
            diff = _json(r["diff"])
            found.setdefault(str(r["ai_action_id"]), []).append(DecisionRecord(
                id=str(r["id"]), ai_action_id=str(r["ai_action_id"]),
                decided_by=str(r["decided_by"]), decision=r["decision"],
                decided_at=r["decided_at"], decided_by_name=r["display_name"],
                diff=diff if isinstance(diff, dict) else None, reason=r["reason"]))
        return found

    async def links_for(self, action_ids: Iterable[str]) -> dict[str, list[LinkRecord]]:
        rows = await self._pool.fetch(
            """
            SELECT ai_action_id, evidence_id, attestation_id, delta, observed_at
            FROM outcome_links WHERE ai_action_id = ANY($1::uuid[])
            ORDER BY observed_at, evidence_id NULLS LAST, attestation_id NULLS LAST
            """, _uuids(action_ids))
        found: dict[str, list[LinkRecord]] = {}
        for r in rows:
            delta = _json(r["delta"])
            found.setdefault(str(r["ai_action_id"]), []).append(LinkRecord(
                ai_action_id=str(r["ai_action_id"]), observed_at=r["observed_at"],
                evidence_id=_str(r["evidence_id"]), attestation_id=_str(r["attestation_id"]),
                delta=delta if isinstance(delta, dict) else None))
        return found

    async def criterion_ids(self, pairs: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], str]:
        rubrics = sorted({r for r, _ in pairs if as_uuid(r)})
        if not rubrics:
            return {}
        rows = await self._pool.fetch(
            "SELECT id, rubric_id, key FROM rubric_criteria WHERE rubric_id = ANY($1::uuid[])",
            rubrics)
        return {(str(r["rubric_id"]), r["key"].lower()): str(r["id"]) for r in rows}

    async def source_titles(self, refs: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], str]:
        by_type: dict[str, list[str]] = {}
        for kind, ref in refs:
            if kind in TITLED_SOURCES and as_uuid(ref):
                by_type.setdefault(kind, []).append(ref)
        titles: dict[tuple[str, str], str] = {}
        for kind, ids in by_type.items():
            rows = await self._pool.fetch(_TITLE_QUERIES[kind], ids)
            titles.update({(kind, str(r["id"])): r["title"] for r in rows if r["title"]})
        return titles

    async def program(self, program_id: str) -> Program | None:
        pid = as_uuid(program_id)
        if pid is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT id, title, COALESCE(metadata->'program_lead_ids', '[]'::jsonb) AS leads"
            " FROM nodes WHERE id = $1::uuid AND kind = 'program'", pid)
        if row is None:
            return None
        courses = await self._pool.fetch(
            "SELECT DISTINCT c.id FROM edges e JOIN nodes c ON c.id = e.from_node"
            " WHERE e.kind = 'part_of' AND c.kind = 'course' AND e.to_node = $1::uuid", pid)
        leads = _json(row["leads"])
        return Program(str(row["id"]), row["title"],
                       frozenset(str(x) for x in leads if isinstance(x, str))
                       if isinstance(leads, list) else frozenset(),
                       frozenset(str(r["id"]) for r in courses))

    async def learner_release(self, actions: Iterable[ActionRecord]) -> LearnerRelease:
        actions = list(actions)
        grades = _uuids(a.target_id for a in actions
                        if a.action_type == "grade_draft" and a.target_type == "grades"
                        and a.target_id)
        feedback = _uuids(a.id for a in actions if a.action_type == "criterion_feedback")
        committed = await self._pool.fetch(
            "SELECT id FROM grades WHERE id = ANY($1::uuid[]) AND NOT is_draft",
            grades) if grades else []
        released = await self._pool.fetch(
            """
            SELECT cs.ai_action_id, cs.criterion_id, cs.ai_score, cs.ai_rationale,
                   cs.ai_evidence_spans, s.status,
                   COALESCE(s.course_node::text, a.metadata->>'course_id') AS course_id
            FROM criterion_scores cs
            JOIN submissions s ON s.id = cs.submission_id
            LEFT JOIN nodes a ON a.id = s.assignment_node
            WHERE cs.ai_action_id = ANY($1::uuid[]) AND cs.released_at IS NOT NULL
            """, feedback) if feedback else []
        hides = _DraftScoreHiding(self._pool)
        by_action: dict[str, dict[str, ReleasedCriterion]] = {}
        for r in released:
            hide = r["status"] == "draft" and await hides.hidden(r["course_id"])
            spans = _json(r["ai_evidence_spans"])
            by_action.setdefault(str(r["ai_action_id"]), {})[str(r["criterion_id"])] = \
                ReleasedCriterion(r["ai_score"], r["ai_rationale"],
                                  spans if isinstance(spans, list) else [], hide)
        return LearnerRelease(frozenset(str(r["id"]) for r in committed),
                              frozenset(by_action), by_action)

    async def learner_link_targets(self, links: Iterable[LinkRecord]) -> LinkTargets:
        links = list(links)
        evidence = _uuids(link.evidence_id for link in links if link.evidence_id)
        pairs = sorted({pair for link in links if (pair := _score_pair(link)) is not None})
        hides = _DraftScoreHiding(self._pool)
        seen_evidence: dict[str, float | None] = {}
        if evidence:
            rows = await self._pool.fetch(
                """
                SELECT e.id, e.visibility, cs.id AS score_id, cs.ai_score,
                       cs.released_at IS NOT NULL AS released, cs.final_score, s.status,
                       COALESCE(s.course_node::text, a.metadata->>'course_id') AS course_id,
                       EXISTS (SELECT 1 FROM grades g WHERE g.submission_id = cs.submission_id
                               AND NOT g.is_draft) AS committed
                FROM evidence e
                LEFT JOIN criterion_scores cs ON cs.id = e.criterion_score_id
                LEFT JOIN submissions s ON s.id = cs.submission_id
                LEFT JOIN nodes a ON a.id = s.assignment_node
                WHERE e.id = ANY($1::uuid[])
                """, evidence)
            for r in rows:
                if r["visibility"] not in SHARED_EVIDENCE:
                    continue
                if r["score_id"] is None:
                    seen_evidence[str(r["id"])] = None
                elif await _score_visible(r, hides):
                    seen_evidence[str(r["id"])] = _seen_score(r)
        seen_scores: dict[tuple[str, str], float | None] = {}
        if pairs:
            rows = await self._pool.fetch(
                """
                SELECT cs.submission_id, cs.criterion_id, cs.ai_score,
                       cs.released_at IS NOT NULL AS released, cs.final_score, s.status,
                       COALESCE(s.course_node::text, a.metadata->>'course_id') AS course_id,
                       EXISTS (SELECT 1 FROM grades g WHERE g.submission_id = cs.submission_id
                               AND NOT g.is_draft) AS committed
                FROM criterion_scores cs
                JOIN submissions s ON s.id = cs.submission_id
                LEFT JOIN nodes a ON a.id = s.assignment_node
                JOIN unnest($1::uuid[], $2::uuid[]) AS p(submission_id, criterion_id)
                  ON p.submission_id = cs.submission_id AND p.criterion_id = cs.criterion_id
                """, [p[0] for p in pairs], [p[1] for p in pairs])
            for r in rows:
                if await _score_visible(r, hides):
                    seen_scores[(str(r["submission_id"]), str(r["criterion_id"]))] = (
                        _seen_score(r))
        return LinkTargets(seen_evidence, seen_scores)


class _DraftScoreHiding:
    """feedback.show_scores_on_drafts per course, read once per course."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._settings = PgFormativeStore(pool)
        self._hidden: dict[str, bool] = {}

    async def hidden(self, course_id: Any) -> bool:
        course = as_uuid(course_id) or ""
        if course not in self._hidden:
            self._hidden[course] = not await show_scores_on_drafts(self._settings,
                                                                   course or None)
        return self._hidden[course]


async def _score_visible(row: asyncpg.Record, hides: _DraftScoreHiding) -> bool:
    """A committed grade's final score, or a released AI score whose course shows it."""
    if row["final_score"] is not None:
        return bool(row["committed"])
    if not row["released"]:
        return False
    return not (row["status"] == "draft" and await hides.hidden(row["course_id"]))


def _seen_score(row: asyncpg.Record) -> float | None:
    """The score of a row `_score_visible` passed."""
    return _num(row["final_score"] if row["committed"] and row["final_score"] is not None
                else row["ai_score"])


def _score_pair(link: LinkRecord) -> tuple[str, str] | None:
    """(submission_id, criterion_id) of a rescore link: one with no evidence or attestation."""
    if link.evidence_id or link.attestation_id:
        return None
    delta = link.delta or {}
    submission, criterion = as_uuid(delta.get("submission_id")), as_uuid(
        delta.get("criterion_id"))
    return (submission, criterion) if submission and criterion else None


# --- aggregation ---------------------------------------------------------------------------


def is_failed_run(action: ActionRecord) -> bool:
    """A feedback run that saved nothing (engine.formative.store.FAILED); not a draft anyone
    could decide on, so it is left out of the rates."""
    return action.action_type == "criterion_feedback" and action.output.get(FAILED) is True


def latest_decision(decisions: list[DecisionRecord] | None) -> DecisionRecord | None:
    return decisions[-1] if decisions else None


def _criterion_rejected(criterion_id: str, decisions: list[DecisionRecord]) -> bool:
    """Whether the latest decision on this criterion is a rejection. A decision naming no
    criterion in `diff.criterion_id` applies to every criterion of the action."""
    mine = [d for d in decisions
            if (d.diff or {}).get("criterion_id") in (None, criterion_id)]
    return bool(mine) and mine[-1].decision == REJECTED


def _edited_next_step(criterion_id: str, decisions: list[DecisionRecord]) -> str | None:
    for d in reversed(decisions):
        if d.decision != EDITED or (d.diff or {}).get("criterion_id") not in (None, criterion_id):
            continue
        edited = ((d.diff or {}).get("fields") or {}).get("next_step")
        if isinstance(edited, dict) and isinstance(edited.get("after"), str):
            return edited["after"]
    return None


def learner_feedback_output(action: ActionRecord, decisions: list[DecisionRecord],
                            release: LearnerRelease) -> dict[str, Any] | None:
    """A criterion_feedback action's output as its learner was given it, or None when no
    criterion of it reached them. Only released, unrejected criteria are kept, carrying the
    released score, rationale and spans and the instructor's edited next step; engine
    annotations (dropped spans) are left out."""
    if action.id not in release.released_actions:
        return None
    items = action.output.get("criteria")
    if not isinstance(items, list):
        latest = latest_decision(decisions)
        return None if latest is not None and latest.decision == REJECTED else action.output
    rows = release.released_criteria.get(action.id)
    kept = []
    for item in items:
        cid = item.get("criterion_id") if isinstance(item, dict) else None
        if not isinstance(cid, str) or _criterion_rejected(cid, decisions):
            continue
        if rows is None:
            kept.append(item)
            continue
        row = rows.get(cid)
        if row is None:
            continue
        kept.append({**item, "ai_score": None if row.hide_score else row.ai_score,
                     "ai_rationale": row.ai_rationale, "evidence_spans": row.evidence_spans,
                     "next_step": _edited_next_step(cid, decisions) or item.get("next_step")})
    if not kept:
        return None
    output = {k: v for k, v in action.output.items() if k != "dropped_spans"}
    return {**output, "criteria": kept}


def learner_action(action: ActionRecord, decisions: list[DecisionRecord],
                   release: LearnerRelease) -> ActionRecord | None:
    """`action` as the learner-facing log (the subject, or their advisor) may list it, or
    None when hidden. Grade drafts appear once their grade is committed and criterion
    feedback per released criterion (`learner_feedback_output`); rejected ones never do.
    Other action types are always visible."""
    if action.action_type not in FEEDBACK_TYPES:
        return action
    if action.action_type == "criterion_feedback":
        output = learner_feedback_output(action, decisions, release)
        return None if output is None else replace(action, output=output)
    latest = latest_decision(decisions)
    if latest is not None and latest.decision == REJECTED:
        return None
    if action.target_type == "grades" and action.target_id in release.committed_grades:
        return action
    return None


def _shown_criteria(action: ActionRecord) -> dict[str, float | None] | None:
    """Criterion id -> score shown by the learner-view output of a criterion_feedback action,
    for the criteria it scores; None when the action does not list criteria."""
    items = action.output.get("criteria")
    if action.action_type != "criterion_feedback" or not isinstance(items, list):
        return None
    return {cid: _num(item.get("ai_score")) for item in items if isinstance(item, dict)
            and item.get("ai_score") is not None
            and (cid := as_uuid(item.get("criterion_id"))) is not None}


def _as_shown(link: LinkRecord, before: float | None, after: float | None) -> LinkRecord:
    """`link` with its criterion before/after (and change, under either key) set to the
    scores the learner sees now, which may differ from those stored when it was linked."""
    delta = dict(link.delta or {})
    change = after - before if before is not None and after is not None else None
    delta.update(before=before, after=after)
    for key in ("change", "delta"):
        if key in delta:
            delta[key] = change
    return replace(link, delta=delta)


def learner_links(action: ActionRecord, links: list[LinkRecord], targets: LinkTargets
                  ) -> list[LinkRecord]:
    """The links of a learner-view `action` whose observation the learner can see: an
    attestation, evidence in `targets`, or a criterion score in `targets`. A link on a
    criterion the learner-view output does not score is left out. A criterion link's before
    and after are replaced by the scores the learner sees now (see `_as_shown`)."""
    shown = _shown_criteria(action)
    kept = []
    for link in links:
        seen: float | None = None
        if link.attestation_id:
            visible = True
        elif link.evidence_id:
            evidence = as_uuid(link.evidence_id)
            visible = evidence in targets.evidence
            seen = targets.evidence.get(evidence or "")
        else:
            pair = _score_pair(link)
            visible = pair is not None and pair in targets.scores
            seen = targets.scores.get(pair) if pair is not None else None
        criterion = as_uuid((link.delta or {}).get("criterion_id"))
        if not visible or (shown is not None and criterion is not None
                           and criterion not in shown):
            continue
        if criterion is not None and not link.attestation_id:
            link = _as_shown(link, shown.get(criterion) if shown else None, seen)
        kept.append(link)
    return kept


def practice_counts(actions: Iterable[ActionRecord],
                    decisions: dict[str, list[DecisionRecord]]) -> dict[str, int]:
    """PracticeCounts: practice sets generated, and those whose learner's latest decision
    is Start (accepted) or Not helpful (dismissed)."""
    sets = [a for a in actions if a.action_type == PRACTICE]
    latest = [latest_decision(decisions.get(a.id)) for a in sets]
    return {"generated": len(sets),
            "started": sum(1 for d in latest if d is not None and d.decision == ACCEPTED),
            "dismissed": sum(1 for d in latest if d is not None and d.decision == "dismissed")}


async def learner_visible(store: MeasurementStore, actions: list[ActionRecord]
                          ) -> list[ActionRecord]:
    """`actions` through `learner_action`, hidden ones dropped, order kept."""
    if not any(a.action_type in FEEDBACK_TYPES for a in actions):
        return actions
    decisions = await store.decisions_for([a.id for a in actions])
    release = await store.learner_release(actions)
    shown = (learner_action(a, decisions.get(a.id, []), release) for a in actions)
    return [a for a in shown if a is not None]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def decision_rates(decided: Iterable[str | None], *, agent: str | None = None,
                   action_type: str | None = None) -> dict[str, Any]:
    """DecisionRates over latest decisions (None = undecided). Rates are over decided items."""
    counts = {ACCEPTED: 0, EDITED: 0, REJECTED: 0, "other": 0, "undecided": 0}
    total = 0
    for value in decided:
        total += 1
        if value is None:
            counts["undecided"] += 1
        elif value in (ACCEPTED, EDITED, REJECTED):
            counts[value] += 1
        else:
            counts["other"] += 1
    n = total - counts["undecided"]
    return {"agent": agent, "action_type": action_type, "total": total, **counts,
            "acceptance_rate": _rate(counts[ACCEPTED], n), "edit_rate": _rate(counts[EDITED], n),
            "reject_rate": _rate(counts[REJECTED], n)}


def criterion_uuid(rubric_id: str | None, key: str) -> str:
    """Stand-in id for a criterion with no `rubric_criteria` row: stable per (rubric, key)."""
    return str(uuid.uuid5(_NAMESPACE, f"criterion:{rubric_id or ''}:{key.lower()}"))


def action_rubric(action: ActionRecord) -> str | None:
    rubric = as_uuid(action.output.get("rubric_id"))
    if rubric:
        return rubric
    return next((as_uuid(s.get("id")) for s in action.sources
                 if s.get("type") == "rubric" and as_uuid(s.get("id"))), None)


def criterion_changes(diff: dict[str, Any] | None
                      ) -> dict[str, tuple[float | None, str | None]] | None:
    """Changed criteria in a decision diff as key -> (score delta, rubric id).

    Reads both diff shapes in use: `{criteria: {key: {before, after, delta}}}` (engine) and
    `{criteria: [{key, rubric_id, delta, ...}]}` (seed). None when the diff has no criteria.
    """
    criteria = (diff or {}).get("criteria")
    changes: dict[str, tuple[float | None, str | None]] = {}
    if isinstance(criteria, dict):
        for key, item in criteria.items():
            changes[str(key)] = (_num(item.get("delta")) if isinstance(item, dict) else None,
                                 None)
    elif isinstance(criteria, list):
        for item in criteria:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                changes[item["key"]] = (_num(item.get("delta")), as_uuid(item.get("rubric_id")))
    else:
        return None
    return changes


def link_change(delta: dict[str, Any] | None) -> float | None:
    """`change`, else `after - before`, when numeric."""
    if not delta:
        return None
    change = _num(delta.get("change"))
    if change is not None:
        return change
    before, after = _num(delta.get("before")), _num(delta.get("after"))
    return after - before if before is not None and after is not None else None


@dataclass
class _CriterionStat:
    key: str
    scored: int = 0
    edits: int = 0
    n_delta: int = 0
    sum_delta: float = 0.0


def criterion_pairs(actions: Iterable[ActionRecord],
                    decisions: dict[str, list[DecisionRecord]]) -> set[tuple[str, str]]:
    """The (rubric_id, key) pairs `summarize` will need ids for."""
    pairs: set[tuple[str, str]] = set()
    for action, changes, scored in _criterion_inputs(actions, decisions):
        rubric = action_rubric(action)
        for key in scored | set(changes):
            pairs.add((changes.get(key, (None, None))[1] or rubric or "", key.lower()))
    return pairs


_CriterionInput = tuple[ActionRecord, dict[str, tuple[float | None, str | None]], set[str]]


def _criterion_inputs(actions: Iterable[ActionRecord],
                      decisions: dict[str, list[DecisionRecord]]
                      ) -> Iterator[_CriterionInput]:
    """Decided feedback drafts whose final criterion scores are known: accepted ones (every
    criterion unchanged) and those whose decision diff lists the changed criteria."""
    for action in actions:
        if action.action_type not in FEEDBACK_TYPES:
            continue
        latest = latest_decision(decisions.get(action.id))
        if latest is None or latest.decision in _NO_FINAL_SCORES:
            continue
        changes = criterion_changes(latest.diff)
        if changes is None:
            if latest.decision != ACCEPTED:
                continue
            changes = {}
        scores = action.output.get("scores")
        scored = {str(k) for k in scores} if isinstance(scores, dict) else set()
        yield action, changes, scored


def summarize(actions: list[ActionRecord], decisions: dict[str, list[DecisionRecord]],
              links: dict[str, list[LinkRecord]],
              criterion_id: Callable[[str | None, str], str]) -> dict[str, Any]:
    """The rates, criterion and learning-delta parts of a MeasurementSummary.

    Criterion means count an unchanged criterion as a 0 delta. Learning deltas are over
    feedback drafts' outcome links, in the units of the observation that was linked.
    """
    actions = [a for a in actions if not is_failed_run(a)]
    by_kind: dict[tuple[str, str], list[str | None]] = {}
    for action in actions:
        latest = latest_decision(decisions.get(action.id))
        by_kind.setdefault((action.agent, action.action_type), []).append(
            latest.decision if latest else None)
    rates = [decision_rates(values, agent=agent, action_type=kind)
             for (agent, kind), values in sorted(by_kind.items())]

    stats: dict[str, _CriterionStat] = {}
    for action, changes, scored in _criterion_inputs(actions, decisions):
        rubric = action_rubric(action)
        for key in sorted(scored | set(changes)):
            delta, changed_rubric = changes.get(key, (0.0, None))
            cid = criterion_id(changed_rubric or rubric, key)
            stat = stats.setdefault(cid, _CriterionStat(key))
            stat.scored += 1
            if key in changes:
                stat.edits += 1
            if delta is not None:
                stat.n_delta += 1
                stat.sum_delta += delta
    score_changes = [
        {"criterion_id": cid, "criterion_key": s.key, "n": s.n_delta,
         "mean_delta": round(s.sum_delta / s.n_delta, 3)}
        for cid, s in sorted(stats.items(), key=lambda kv: (kv[1].key, kv[0])) if s.n_delta
    ]
    edited = sorted(((cid, s) for cid, s in stats.items() if s.edits),
                    key=lambda kv: (-kv[1].edits, -kv[1].edits / kv[1].scored, kv[1].key))
    most_edited = [{"criterion_id": cid, "criterion_key": s.key, "edit_count": s.edits,
                    "edit_rate": round(s.edits / s.scored, 4)}
                   for cid, s in edited[:MOST_EDITED_LIMIT]]

    learning: dict[str, list[float]] = {ACCEPTED: [], EDITED: [], REJECTED: []}
    for action in actions:
        latest = latest_decision(decisions.get(action.id))
        if action.action_type not in FEEDBACK_TYPES or latest is None \
                or latest.decision not in learning:
            continue
        for link in links.get(action.id, []):
            change = link_change(link.delta)
            if change is not None:
                learning[latest.decision].append(change)
    learning_delta = {k: {"n": len(v), "mean_delta": round(sum(v) / len(v), 3) if v else None}
                      for k, v in learning.items()}
    return {"rates": rates, "criterion_score_changes": score_changes,
            "learning_delta_by_decision": learning_delta, "most_edited_criteria": most_edited}


async def criterion_resolver(store: MeasurementStore, actions: list[ActionRecord],
                             decisions: dict[str, list[DecisionRecord]]
                             ) -> Callable[[str | None, str], str]:
    known = await store.criterion_ids(criterion_pairs(actions, decisions))

    def resolve(rubric_id: str | None, key: str) -> str:
        return known.get((rubric_id or "", key.lower())) or criterion_uuid(rubric_id, key)

    return resolve


# --- serialization -------------------------------------------------------------------------


def pseudonymous_id(person_id: str) -> str:
    """A UUID standing in for a person: derived from the gateway's salted pseudonym, so it is
    stable for a salt and cannot be mapped back without it."""
    return str(uuid.uuid5(_NAMESPACE, pseudonym(person_id)))


def _replace_id(value: Any, person_id: str, alias: str) -> Any:
    if isinstance(value, dict):
        return {k: _replace_id(v, person_id, alias) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_id(v, person_id, alias) for v in value]
    if isinstance(value, str):
        return value.replace(person_id, alias)
    return value


def decision_out(d: DecisionRecord, hide: str | None = None, *,
                 learner_view: bool = False) -> dict[str, Any]:
    """HumanDecision; `hide` is a learner id to pseudonymize when they are the decider.
    `learner_view` drops the reviewer's diff and reason."""
    diff, reason = d.diff, d.reason
    if learner_view:
        diff, reason = None, None
    elif hide is not None:
        alias = pseudonymous_id(hide)
        diff = _replace_id(scan_and_redact_result(diff).value, hide, alias)
        reason = _replace_id(scan_and_redact_result(reason).value, hide, alias)
    hidden = hide is not None and d.decided_by == hide
    return {
        "id": d.id, "ai_action_id": d.ai_action_id,
        "decided_by": pseudonymous_id(d.decided_by) if hidden else d.decided_by,
        "decided_by_name": pseudonym(d.decided_by) if hidden else d.decided_by_name,
        "decision": d.decision, "diff": diff, "reason": reason,
        "decided_at": d.decided_at.isoformat(),
    }


def link_out(link: LinkRecord) -> dict[str, Any]:
    return {"ai_action_id": link.ai_action_id, "evidence_id": link.evidence_id,
            "attestation_id": link.attestation_id, "delta": link.delta,
            "observed_at": link.observed_at.isoformat()}


# Output keys holding the learner's profile or text derived from it. They are shown only to
# the subject: anyone else reads the profile through endpoints that write data_access_log.
PROFILE_BEARING_KEYS = ("profile_md", "insights", "script")


def withhold_profile(action: ActionRecord, viewer_id: str) -> dict[str, Any]:
    """`action.output`, minus its profile-bearing keys unless `viewer_id` is the subject.
    Withheld keys are listed under `withheld`."""
    output = action.output
    if action.subject_person is not None and action.subject_person == viewer_id:
        return output
    hidden = [k for k in PROFILE_BEARING_KEYS if k in output]
    if not hidden or action.action_type not in ("profile_update", "generation"):
        return output
    return {**{k: v for k, v in output.items() if k not in hidden}, "withheld": hidden}


def action_out(action: ActionRecord, decisions: list[DecisionRecord],
               links: list[LinkRecord], titles: dict[tuple[str, str], str], *,
               viewer_id: str, pseudonymize: bool = False,
               learner_view: bool = False) -> dict[str, Any]:
    """AiAction as `viewer_id` may see it (see `withhold_profile`). With `pseudonymize`, the
    subject learner's id and name are replaced in every field and the output gets the PII
    filter. `learner_view` is the subject's or advisor's view (see `decision_out`)."""
    subject = action.subject_person if pseudonymize else None
    output: Any = withhold_profile(action, viewer_id)
    target_id = action.target_id
    if subject is not None:
        alias = pseudonymous_id(subject)
        output = _replace_id(scan_and_redact_result(output).value, subject, alias)
        if target_id == subject:
            target_id = alias
    sources = [{**s, "title": titles.get((str(s.get("type")), str(s.get("id"))))}
               for s in action.sources]
    return {
        "id": action.id, "session_id": action.session_id, "turn_id": action.turn_id,
        "agent": action.agent, "action_type": action.action_type,
        "subject_person_id": pseudonymous_id(subject) if subject else action.subject_person,
        "course_id": action.course_node, "target_type": action.target_type,
        "target_id": target_id, "sources": sources, "policies": list(action.policies),
        "model": action.model, "prompt_sha256": action.prompt_sha256, "output": output,
        "created_at": action.created_at.isoformat(),
        "decisions": [decision_out(d, subject, learner_view=learner_view) for d in decisions],
        "outcome_links": [link_out(link) for link in links],
    }


def source_refs(actions: Iterable[ActionRecord]) -> set[tuple[str, str]]:
    return {(str(s.get("type")), str(s.get("id"))) for a in actions for s in a.sources
            if s.get("type") in TITLED_SOURCES and s.get("id")}
