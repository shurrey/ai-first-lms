"""Provenance write points (spec.md §6.3-6.4): `ai_actions` and `human_decisions`.

`ProvenanceRecorder` turns a finished tool call, background analysis or podcast into rows.
Every row id is a UUIDv5 of the call that produced it, so a retried write is a no-op.
`tool_succeeded`, `tool_rejected` and the `*_safely` methods never raise: a failed write is
logged at ERROR and the caller continues.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

import asyncpg

from engine.logging_config import get_logger
from engine.turn_repository import turn_db_id

log = get_logger(__name__)

ActionType = Literal["generation", "grade_draft", "criterion_feedback", "practice_item",
                     "recommendation", "attestation", "profile_update", "nudge", "alert"]
DecisionValue = Literal["accepted", "edited", "rejected", "overridden", "dismissed",
                        "disputed", "snoozed"]
SourceType = Literal["content_item", "node", "submission", "rubric", "policy"]

_NAMESPACE = uuid.UUID("5d0c7a52-3f7e-4b8e-a3a1-6c1f4e2b9d70")
MAX_SOURCES = 50
SUPERSEDED_REASON = "A later draft of this grade was committed instead."

# criterion_feedback and practice_item (Phase 2) and nudge/alert (Phase 4) are written by
# their flows when those exist. `policies` stays [] until the Phase 3 resolver (spec.md §8.5).

GRADE = ("grades", "assessments.draft_grade")
PENDING_CREDENTIALS = "pending_credentials"
PROFILE_TOOLS = frozenset({"roster.update_learner_profile", "roster.update_student_insights"})
GENERATION_TOOLS: dict[str, tuple[str, str]] = {  # tool -> (target_type, id key in result)
    "content.save_skill": ("content_items", "id"),
    "content.save_draft": ("content_items", "draft_id"),
    "assessments.create_question": ("questions", "question_id"),
}
# Output fields kept from a generating call's arguments; identity overwrites are dropped.
GENERATION_FIELDS: dict[str, tuple[str, ...]] = {
    "content.save_skill": ("concept_id", "body_md"),
    "content.save_draft": ("node_id", "kind", "title", "body_md"),
    "assessments.create_question": ("bank_id", "type", "stem", "options", "answer_key",
                                    "bloom_level", "difficulty", "aligned_nodes"),
}
GRADE_FIELDS = ("submission_id", "rubric_id", "scores", "feedback", "holistic_md")


def as_uuid(value: Any) -> str | None:
    """Canonical UUID text, or None for anything that is not one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "|".join(parts)))


def _jsonable(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=_jsonable)


def prompt_sha256(system: str, messages: list[Any]) -> str:
    """Hash of a model request's system prompt and messages, exactly as sent."""
    return hashlib.sha256(canonical_json({"system": system, "messages": messages})
                          .encode()).hexdigest()


def source(kind: SourceType, object_id: Any, version: Any = None) -> dict[str, Any] | None:
    oid = as_uuid(object_id)
    return {"type": kind, "id": oid, "version": version} if oid else None


# --- rows ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class AiActionRow:
    id: str
    agent: str
    action_type: ActionType
    output: dict[str, Any]
    session_id: str | None = None
    turn_id: str | None = None  # engine turn id; stored under turn_db_id
    subject_person: str | None = None
    course_node: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    prompt_sha256: str | None = None


@dataclass(frozen=True)
class StoredAction:
    id: str
    agent: str
    action_type: str
    subject_person: str | None
    course_node: str | None
    target_type: str | None
    target_id: str | None
    output: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class HumanDecisionRow:
    id: str
    ai_action_id: str
    decided_by: str
    decision: DecisionValue
    diff: dict[str, Any] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class StoredDecision:
    id: str
    ai_action_id: str
    decided_by: str
    decision: str
    diff: dict[str, Any] | None
    reason: str | None
    decided_at: datetime


class ProvenanceStore(Protocol):
    async def record_action(self, row: AiActionRow) -> bool:
        """False when a row with this id already exists. Unknown session, turn, person or
        course ids are stored as NULL."""
        ...

    async def record_decision(self, row: HumanDecisionRow) -> bool:
        """False when a row with this id already exists."""
        ...

    async def get_action(self, action_id: str) -> StoredAction | None: ...

    async def find_actions(
        self, action_type: str, *, target_type: str | None = None,
        target_id: str | None = None, output_key: str | None = None,
        output_value: str | None = None,
    ) -> list[StoredAction]:
        """Matching actions, oldest first."""
        ...

    async def decisions(self, action_id: str) -> list[StoredDecision]:
        """Oldest first."""
        ...

    async def pending_credential_id(self, person_id: str, microcredential_id: str
                                    ) -> str | None:
        """The pending (not yet reviewed) row for this learner and microcredential."""
        ...


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _str(value: Any) -> str | None:
    return str(value) if value is not None else None


class PgProvenanceStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_action(self, row: AiActionRow) -> bool:
        turn = turn_db_id(row.turn_id) if row.turn_id else None
        status = await self._pool.execute(
            """
            INSERT INTO ai_actions (id, session_id, turn_id, agent, action_type, subject_person,
                                    course_node, target_type, target_id, sources, policies,
                                    model, prompt_sha256, output)
            VALUES ($1,
                    (SELECT id FROM sessions WHERE id = $2::uuid),
                    (SELECT id FROM turns WHERE id = $3::uuid),
                    $4, $5,
                    (SELECT id FROM persons WHERE id = $6::uuid),
                    (SELECT id FROM nodes WHERE id = $7::uuid),
                    $8, $9::uuid, $10::jsonb, $11::jsonb, $12, $13, $14::jsonb)
            ON CONFLICT (id) DO NOTHING
            """,
            uuid.UUID(row.id), as_uuid(row.session_id), turn, row.agent, row.action_type,
            as_uuid(row.subject_person), as_uuid(row.course_node), row.target_type,
            as_uuid(row.target_id), canonical_json(row.sources), canonical_json(row.policies),
            row.model, row.prompt_sha256, canonical_json(row.output),
        )
        return bool(status == "INSERT 0 1")

    async def record_decision(self, row: HumanDecisionRow) -> bool:
        status = await self._pool.execute(
            """
            INSERT INTO human_decisions (id, ai_action_id, decided_by, decision, diff, reason)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            ON CONFLICT (id) DO NOTHING
            """,
            uuid.UUID(row.id), uuid.UUID(row.ai_action_id), uuid.UUID(row.decided_by),
            row.decision, canonical_json(row.diff) if row.diff is not None else None,
            row.reason,
        )
        return bool(status == "INSERT 0 1")

    @staticmethod
    def _action(row: asyncpg.Record) -> StoredAction:
        return StoredAction(
            id=str(row["id"]), agent=row["agent"], action_type=row["action_type"],
            subject_person=_str(row["subject_person"]), course_node=_str(row["course_node"]),
            target_type=row["target_type"], target_id=_str(row["target_id"]),
            output=_json(row["output"]) or {}, created_at=row["created_at"],
        )

    async def get_action(self, action_id: str) -> StoredAction | None:
        aid = as_uuid(action_id)
        if aid is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT id, agent, action_type, subject_person, course_node, target_type,"
            " target_id, output, created_at FROM ai_actions WHERE id = $1::uuid", aid)
        return self._action(row) if row else None

    async def find_actions(
        self, action_type: str, *, target_type: str | None = None,
        target_id: str | None = None, output_key: str | None = None,
        output_value: str | None = None,
    ) -> list[StoredAction]:
        rows = await self._pool.fetch(
            """
            SELECT id, agent, action_type, subject_person, course_node, target_type,
                   target_id, output, created_at
            FROM ai_actions
            WHERE action_type = $1
              AND ($2::text IS NULL OR target_type = $2)
              AND ($3::uuid IS NULL OR target_id = $3::uuid)
              AND ($4::text IS NULL OR output ->> $4 = $5)
            ORDER BY created_at, id
            """,
            action_type, target_type, as_uuid(target_id) if target_id else None,
            output_key, output_value,
        )
        return [self._action(r) for r in rows]

    async def decisions(self, action_id: str) -> list[StoredDecision]:
        aid = as_uuid(action_id)
        if aid is None:
            return []
        rows = await self._pool.fetch(
            "SELECT id, ai_action_id, decided_by, decision, diff, reason, decided_at"
            " FROM human_decisions WHERE ai_action_id = $1::uuid ORDER BY decided_at, id", aid)
        return [StoredDecision(str(r["id"]), str(r["ai_action_id"]), str(r["decided_by"]),
                               r["decision"], _json(r["diff"]), r["reason"], r["decided_at"])
                for r in rows]

    async def pending_credential_id(self, person_id: str, microcredential_id: str
                                    ) -> str | None:
        pid, mid = as_uuid(person_id), as_uuid(microcredential_id)
        if pid is None or mid is None:
            return None
        found = await self._pool.fetchval(
            "SELECT id FROM pending_credentials WHERE person_id = $1::uuid"
            " AND microcredential_id = $2::uuid AND status = 'pending'"
            " ORDER BY created_at DESC LIMIT 1", pid, mid)
        return _str(found)


# --- diffs ---------------------------------------------------------------------------------


def text_edit_stats(before: str, after: str) -> dict[str, Any]:
    """`edit_chars` counts characters in difflib's changed spans: an upper bound on the
    Levenshtein distance, not the exact value."""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    edits = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes()
                if tag != "equal")
    return {"chars_before": len(before), "chars_after": len(after), "edit_chars": edits,
            "similarity": round(matcher.ratio(), 3)}


def _score(value: Any) -> Any:
    """A criterion score: a number, or an object carrying one under `score`."""
    if isinstance(value, dict):
        return value.get("score")
    return value


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else canonical_json(value)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def grade_diff(draft: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    """Per-criterion score deltas and feedback edit stats between two grade outputs (each
    with `scores`, `feedback` keyed by criterion, and `holistic_md`). Unchanged criteria are
    omitted; `changed` is False when nothing differs."""
    criteria: dict[str, Any] = {}
    draft_scores, final_scores = _mapping(draft.get("scores")), _mapping(final.get("scores"))
    for key in sorted(set(draft_scores) | set(final_scores)):
        before, after = _score(draft_scores.get(key)), _score(final_scores.get(key))
        if before != after:
            delta = after - before if _number(before) and _number(after) else None
            criteria[key] = {"before": before, "after": after, "delta": delta}
    feedback: dict[str, Any] = {}
    draft_fb, final_fb = _mapping(draft.get("feedback")), _mapping(final.get("feedback"))
    for key in sorted(set(draft_fb) | set(final_fb)):
        before, after = _text(draft_fb.get(key)), _text(final_fb.get(key))
        if before != after:
            feedback[key] = text_edit_stats(before, after)
    holistic_before, holistic_after = _text(draft.get("holistic_md")), _text(
        final.get("holistic_md"))
    holistic = (text_edit_stats(holistic_before, holistic_after)
                if holistic_before != holistic_after else None)
    return {"criteria": criteria, "feedback": feedback, "holistic_md": holistic,
            "changed": bool(criteria or feedback or holistic)}


def fields_diff(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]
                ) -> dict[str, Any]:
    """Which of `keys` an approver changed; text fields carry edit stats."""
    changed: dict[str, Any] = {}
    for key in keys:
        if before.get(key) == after.get(key):
            continue
        a, b = before.get(key), after.get(key)
        changed[key] = (text_edit_stats(a, b) if isinstance(a, str) and isinstance(b, str)
                        else {"before": a, "after": b})
    return {"fields": changed, "changed": bool(changed)}


# --- the sources a run used ----------------------------------------------------------------

# Read tools whose results name what an agent's output drew on.
_RESULT_SOURCES: dict[str, tuple[SourceType, str]] = {
    "content.retrieve": ("content_item", "id"),
    "content.get_skill": ("content_item", "id"),
    "assessments.get_submission": ("submission", "id"),
    "assessments.get_rubric": ("rubric", "id"),
}
_ARG_SOURCES: dict[str, SourceType] = {
    "node_id": "node", "concept_id": "node", "content_id": "content_item",
    "submission_id": "submission", "rubric_id": "rubric",
}
_LIST_SOURCES: dict[str, tuple[str, SourceType]] = {  # tool -> (result list key, type)
    "content.search": ("results", "node"),
    "graph.neighbors": ("nodes", "node"),
    "graph.prerequisites": ("prerequisites", "node"),
}


def sources_from_call(tool: str, args: dict[str, Any], result: dict[str, Any] | None
                      ) -> list[dict[str, Any]]:
    found: list[dict[str, Any] | None] = [source(kind, args.get(key))
                                          for key, kind in _ARG_SOURCES.items()]
    if result is not None:
        if tool in _RESULT_SOURCES:
            kind, key = _RESULT_SOURCES[tool]
            found.append(source(kind, result.get(key), result.get("version")))
        if tool in _LIST_SOURCES:
            key, kind = _LIST_SOURCES[tool]
            items = result.get(key)
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    found.append(source(kind, item.get("id")))
    return [s for s in found if s is not None]


@dataclass
class ProvenanceTrail:
    """What one agent run has used so far: its model, the prompt behind its latest model
    call, and the sources its successful tool calls read. A submission read in the run is
    a source only of actions about its owner. Single event loop only."""

    model: str | None = None
    prompt_sha256: str | None = None
    _sources: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    _submission_owners: dict[str, str] = field(default_factory=dict)

    def observe(self, tool: str, args: dict[str, Any], result: dict[str, Any] | None) -> None:
        if tool == "assessments.get_submission" and result is not None:
            sub, owner = as_uuid(result.get("id")), as_uuid(result.get("person_id"))
            if sub and owner:
                self._submission_owners[sub] = owner
        for item in sources_from_call(tool, args, result):
            if len(self._sources) >= MAX_SOURCES:
                return
            self._sources.setdefault((item["type"], item["id"]), item)

    def sources(self, extra: list[dict[str, Any]] | None = None,
                subject: str | None = None) -> list[dict[str, Any]]:
        """The run's sources plus `extra` (the call's own). Run-level submissions are kept
        only when their owner is known to be `subject`."""
        merged = {key: item for key, item in self._sources.items()
                  if key[0] != "submission"
                  or (subject is not None and self._submission_owners.get(key[1]) == subject)}
        for item in extra or []:
            merged.setdefault((item["type"], item["id"]), item)
        return list(merged.values())


# --- the recorder --------------------------------------------------------------------------

SubmissionLookup = Callable[[str], Awaitable[tuple[str | None, str | None]]]


@dataclass(frozen=True)
class ToolCallFacts:
    """A tool call that ran (or was declined at approval), as the gateway saw it.

    `call_key` is unique per (turn, tool call); `proposed` are the arguments before an
    approver's edit, `args` those executed. The recorder appends to `recorded` the id of
    every ai_actions row it writes for the call (a retried write's existing row included).
    """

    agent: str
    tool: str
    call_key: str
    requester_id: str
    args: dict[str, Any]
    proposed: dict[str, Any]
    result: dict[str, Any] | None
    session_id: str = ""
    turn_id: str = ""
    course_id: str = ""
    approval: dict[str, Any] | None = None  # {approval_id, decision, approved_by}
    trail: ProvenanceTrail | None = None
    recorded: list[str] = field(default_factory=list)


def call_key(turn_id: str, call_id: str, tool: str, args: dict[str, Any]) -> str:
    """Without a model tool-use id, identical calls in one turn share a key."""
    turn = str(turn_db_id(turn_id)) if turn_id else "no-turn"
    if call_id:
        return f"{turn}:{call_id}"
    digest = hashlib.sha256(canonical_json([tool, args]).encode()).hexdigest()[:32]
    return f"{turn}:{tool}:{digest}"


def _approver(facts: ToolCallFacts) -> str:
    approved_by = (facts.approval or {}).get("approved_by")
    return approved_by if isinstance(approved_by, str) and approved_by else facts.requester_id


class ProvenanceRecorder:
    def __init__(self, store: ProvenanceStore) -> None:
        self._store = store

    @property
    def store(self) -> ProvenanceStore:
        return self._store

    async def tool_succeeded(self, facts: ToolCallFacts,
                             lookup_submission: SubmissionLookup | None = None) -> None:
        try:
            await self._tool_succeeded(facts, lookup_submission)
        except Exception:
            log.error("provenance_write_failed", tool=facts.tool, agent=facts.agent,
                      turn_id=facts.turn_id, exc_info=True)

    async def tool_rejected(self, facts: ToolCallFacts) -> None:
        """A gated call a person declined at approval."""
        try:
            await self._tool_rejected(facts)
        except Exception:
            log.error("provenance_write_failed", tool=facts.tool, agent=facts.agent,
                      turn_id=facts.turn_id, exc_info=True)

    async def _tool_succeeded(self, facts: ToolCallFacts,
                              lookup_submission: SubmissionLookup | None) -> None:
        tool, result = facts.tool, facts.result or {}
        if tool == GRADE[1]:
            await self._grade_drafted(facts, result, lookup_submission)
        elif tool == "assessments.commit_grade":
            await self._grade_committed(facts)
        elif tool == "attestations.attest":
            await self._attested(facts, result)
        elif tool == "assessments.approve_credential":
            await self.credential_decided(facts.args.get("pending_id"), _approver(facts),
                                          "accepted", facts.call_key)
        elif tool in PROFILE_TOOLS:
            await self._profile_updated(facts)
        elif tool in GENERATION_TOOLS:
            await self._generated(facts, result)

    async def _tool_rejected(self, facts: ToolCallFacts) -> None:
        if facts.tool == "assessments.commit_grade":
            draft = await self._latest(GRADE[0], facts.args.get("grade_id"), "grade_draft")
            if draft is not None:
                await self._decide(draft.id, facts.call_key, _approver(facts), "rejected")
        elif facts.tool == "assessments.approve_credential":
            await self.credential_decided(facts.args.get("pending_id"), _approver(facts),
                                          "rejected", facts.call_key)
        elif facts.tool == "assessments.create_question":
            action = await self._action(facts, "generation", target=None, target_id=None,
                                        output=_pick(facts.proposed,
                                                     GENERATION_FIELDS[facts.tool]))
            await self._decide(action.id, facts.call_key, _approver(facts), "rejected")

    # --- per write point -------------------------------------------------------------------

    async def _action(
        self, facts: ToolCallFacts, action_type: ActionType, *, target: str | None,
        target_id: Any, output: dict[str, Any], subject: str | None = None,
        course: str | None = None, extra_sources: list[dict[str, Any]] | None = None,
        suffix: str = "",
    ) -> AiActionRow:
        trail = facts.trail
        own = sources_from_call(facts.tool, facts.args, None) + list(extra_sources or [])
        row = AiActionRow(
            id=stable_id(facts.call_key, action_type, suffix),
            agent=facts.agent, action_type=action_type, output=output,
            session_id=facts.session_id or None, turn_id=facts.turn_id or None,
            subject_person=subject, course_node=course or as_uuid(facts.course_id),
            target_type=target, target_id=as_uuid(target_id),
            sources=trail.sources(own, subject) if trail else _dedupe(own),
            model=trail.model if trail else None,
            prompt_sha256=trail.prompt_sha256 if trail else None,
        )
        await self.record(row)
        facts.recorded.append(row.id)
        return row

    async def record(self, row: AiActionRow) -> bool:
        """Raises on a store failure; `record_safely` logs it instead."""
        inserted = await self._store.record_action(row)
        log.info("ai_action_recorded", ai_action_id=row.id, action_type=row.action_type,
                 agent=row.agent, target_type=row.target_type, inserted=inserted)
        return inserted

    async def record_safely(self, row: AiActionRow) -> None:
        try:
            await self.record(row)
        except Exception:
            log.error("provenance_write_failed", action_type=row.action_type, agent=row.agent,
                      exc_info=True)

    async def _decide(self, action_id: str, key: str, decided_by: str,
                      decision: DecisionValue, diff: dict[str, Any] | None = None,
                      reason: str | None = None) -> None:
        if as_uuid(decided_by) is None:
            log.warning("human_decision_without_person", ai_action_id=action_id,
                        decision=decision)
            return
        row = HumanDecisionRow(id=stable_id(key, "decision", action_id),
                               ai_action_id=action_id, decided_by=decided_by,
                               decision=decision, diff=diff, reason=reason)
        inserted = await self._store.record_decision(row)
        log.info("human_decision_recorded", ai_action_id=action_id, decision=decision,
                 inserted=inserted)

    async def _latest(self, target_type: str, target_id: Any, action_type: str
                      ) -> StoredAction | None:
        if as_uuid(target_id) is None:
            return None
        found = await self._store.find_actions(action_type, target_type=target_type,
                                               target_id=str(target_id))
        return found[-1] if found else None

    async def _grade_drafted(self, facts: ToolCallFacts, result: dict[str, Any],
                             lookup_submission: SubmissionLookup | None) -> None:
        submission_id = facts.args.get("submission_id")
        owner, course = (None, None)
        if lookup_submission is not None and isinstance(submission_id, str):
            owner, course = await lookup_submission(submission_id)
        output = {"grade_id": result.get("grade_id"), **_pick(facts.args, GRADE_FIELDS)}
        await self._action(facts, "grade_draft", target=GRADE[0],
                           target_id=result.get("grade_id"), output=output, subject=owner,
                           course=as_uuid(course))

    async def _grade_committed(self, facts: ToolCallFacts) -> None:
        """The committed draft is accepted as drafted (commit_grade applies it unchanged).
        Earlier drafts of the same submission with no decision yet are marked edited, with the
        diff to what was committed; a rejected draft keeps its rejection."""
        committed = await self._latest(GRADE[0], facts.args.get("grade_id"), "grade_draft")
        if committed is None:
            log.info("grade_commit_without_draft_action", grade_id=facts.args.get("grade_id"))
            return
        decided_by = _approver(facts)
        final = committed.output
        diff = grade_diff(committed.output, final)
        await self._decide(committed.id, facts.call_key, decided_by,
                           "edited" if diff["changed"] else "accepted", diff)
        submission = committed.output.get("submission_id")
        if not isinstance(submission, str):
            return
        earlier = await self._store.find_actions("grade_draft", output_key="submission_id",
                                                 output_value=submission)
        for draft in earlier:
            if draft.id == committed.id or draft.created_at > committed.created_at:
                continue
            settled = {d.decision for d in await self._store.decisions(draft.id)}
            if settled & {"accepted", "edited", "rejected"}:
                continue
            await self._decide(draft.id, facts.call_key, decided_by, "edited",
                               grade_diff(draft.output, final), SUPERSEDED_REASON)

    async def _attested(self, facts: ToolCallFacts, result: dict[str, Any]) -> None:
        person = facts.args.get("person_id")
        node = facts.args.get("node_id")
        output = {k: result.get(k) for k in ("attestation_id", "level", "previous_level",
                                             "downgraded", "reason") if k in result}
        output.setdefault("level", facts.args.get("level"))
        output["node_id"] = node
        await self._action(facts, "attestation", target="attestations",
                           target_id=result.get("attestation_id"), output=output,
                           subject=as_uuid(person))
        pending = result.get("credentials_pending")
        for item in pending if isinstance(pending, list) else []:
            if not isinstance(item, dict):
                continue
            mc = item.get("microcredential_id")
            pending_id = (await self._store.pending_credential_id(person, mc)
                          if isinstance(person, str) and isinstance(mc, str) else None)
            await self._action(
                facts, "recommendation", target=PENDING_CREDENTIALS, target_id=pending_id,
                output={"kind": "credential", "microcredential_id": mc,
                        "title": item.get("title"), "pending_id": pending_id},
                subject=as_uuid(person), suffix=str(mc),
            )

    async def credential_decided(self, pending_id: Any, decided_by: str,
                                 decision: DecisionValue, key: str) -> None:
        """Approve or reject on a pending credential's badge recommendation. Raises on a
        store failure; `credential_decided_safely` logs it instead."""
        action = await self._latest(PENDING_CREDENTIALS, pending_id, "recommendation")
        if action is None:
            log.info("credential_decision_without_recommendation", pending_id=pending_id)
            return
        await self._decide(action.id, key, decided_by, decision)

    async def credential_decided_safely(self, pending_id: Any, decided_by: str,
                                        decision: DecisionValue, key: str) -> None:
        try:
            await self.credential_decided(pending_id, decided_by, decision, key)
        except Exception:
            log.error("provenance_write_failed", pending_id=pending_id, decision=decision,
                      exc_info=True)

    async def _profile_updated(self, facts: ToolCallFacts) -> None:
        field_name = ("profile_md" if facts.tool == "roster.update_learner_profile"
                      else "insights")
        person = as_uuid(facts.args.get("person_id"))
        await self._action(facts, "profile_update", target="persons", target_id=person,
                           output={"tool": facts.tool, field_name: facts.args.get(field_name)},
                           subject=person)

    async def _generated(self, facts: ToolCallFacts, result: dict[str, Any]) -> None:
        target, id_key = GENERATION_TOOLS[facts.tool]
        fields = GENERATION_FIELDS[facts.tool]
        action = await self._action(facts, "generation", target=target,
                                    target_id=result.get(id_key),
                                    output={"tool": facts.tool, **_pick(facts.proposed, fields)})
        if facts.approval is not None:  # the approval published it to a live bank
            diff = fields_diff(facts.proposed, facts.args, fields)
            await self._decide(action.id, facts.call_key, _approver(facts),
                               "edited" if diff["changed"] else "accepted", diff)


def _pick(args: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: args[k] for k in keys if k in args}


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({(i["type"], i["id"]): i for i in items}.values())
