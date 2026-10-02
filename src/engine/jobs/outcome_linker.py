"""Outcome linker (spec.md §6.4): what happened to a learner's learning after an AI action.

For each anchor of an action about a learner, links the learner's next observation after the
action and within the window, one `outcome_links` row per (action, kind, anchor). The earliest
observation wins (ties by id); a linked anchor is never relinked. See `link_outcomes`.

Only evidence with visibility `course` or `program` is used, for both the before and after
values: `private` evidence (practice) stays with the learner (spec.md §12.5). Attestations
are course-visible by definition and are always used.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from engine.logging_config import get_logger

log = get_logger(__name__)

LEVEL_ORDER = {"emerging": 1, "proficient": 2, "mastery": 3}
# Anchors: node ids in `output.node_id` / `output.node_ids`, and the criteria of the
# `criterion_scores` rows carrying the action's id. `delta` holds kind, anchor, before, after,
# change; `observed_at` is the observation's own time, so a rerun writes identical rows.
# grade_draft outputs carry neither until criterion_scores rows are written for them (T-E-114),
# so live feedback drafts get no links before then.
NODE_EVIDENCE = "node_evidence"  # before: latest evidence score on the node at/before the action
# attestations.attest upserts one row per (person, node), so a later attestation by the same
# learner on the same node keeps the action's own target id and is never linked here.
NODE_ATTESTATION = "node_attestation"  # by node_id or node_set; the action's own target excluded
CRITERION = "criterion"  # evidence whose criterion_score_id scores the criterion (not its own)
SHARED_VISIBILITY = frozenset({"course", "program"})
# Arbitrary constant shared by every linker process; pg advisory locks are database-wide.
ADVISORY_LOCK_KEY = 0x6F75_746C  # "outl"


@dataclass(frozen=True)
class CriterionAnchor:
    criterion_id: str
    key: str | None
    before: float | None
    criterion_score_id: str


@dataclass(frozen=True)
class LinkableAction:
    id: str
    subject: str
    created_at: datetime
    nodes: frozenset[str] = frozenset()
    criteria: tuple[CriterionAnchor, ...] = ()
    own_attestation: str | None = None


@dataclass(frozen=True)
class EvidenceObs:
    id: str
    person: str
    node: str
    score: float | None
    observed_at: datetime
    criterion_id: str | None = None
    criterion_score_id: str | None = None
    criterion_score: float | None = None
    visibility: str = "private"


@dataclass(frozen=True)
class AttestationObs:
    id: str
    person: str
    nodes: frozenset[str]
    level: str
    issued_at: datetime


@dataclass(frozen=True)
class OutcomeLink:
    ai_action_id: str
    delta: dict[str, Any]
    observed_at: datetime
    evidence_id: str | None = None
    attestation_id: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return link_key(self.ai_action_id, self.delta)


def link_key(action_id: str, delta: dict[str, Any] | None) -> tuple[str, str, str]:
    delta = delta or {}
    anchor = delta.get("criterion_id") or delta.get("node_id") or ""
    return (action_id, str(delta.get("kind", "")), str(anchor))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _change(before: float | None, after: float | None) -> float | None:
    return round(after - before, 4) if before is not None and after is not None else None


def _rank_change(before: str | None, after: str) -> int | None:
    b, a = LEVEL_ORDER.get(before or ""), LEVEL_ORDER.get(after)
    return a - b if a is not None and b is not None else None


def link_outcomes(
    actions: Iterable[LinkableAction], evidence: Iterable[EvidenceObs],
    attestations: Iterable[AttestationObs], *, window: timedelta, now: datetime,
    existing: set[tuple[str, str, str]] | None = None,
) -> list[OutcomeLink]:
    """New links only; anchors in `existing` (as `link_key` tuples) are skipped. Pure.

    Window is (created_at, min(created_at + window, now)]. Attestation levels compare
    emerging < proficient < mastery; criterion scores are coalesce(final_score, ai_score).
    Evidence not in SHARED_VISIBILITY is ignored.
    """
    done = set(existing or ())
    evidence = [e for e in evidence if e.visibility in SHARED_VISIBILITY]
    attestations = list(attestations)
    links: list[OutcomeLink] = []

    def add(link: OutcomeLink) -> None:
        if link.key not in done:
            done.add(link.key)
            links.append(link)

    for action in actions:
        start, end = action.created_at, min(action.created_at + window, now)
        mine_ev = [e for e in evidence if e.person == action.subject]
        mine_at = [a for a in attestations if a.person == action.subject]

        for node in sorted(action.nodes):
            on_node = [e for e in mine_ev if e.node == node]
            nxt = min((e for e in on_node if start < e.observed_at <= end),
                      key=lambda e: (e.observed_at, e.id), default=None)
            if nxt is not None:
                prior = max((e for e in on_node if e.observed_at <= start),
                            key=lambda e: (e.observed_at, e.id), default=None)
                before = _number(prior.score) if prior else None
                after = _number(nxt.score)
                add(OutcomeLink(action.id, {"kind": NODE_EVIDENCE, "node_id": node,
                                            "before": before, "after": after,
                                            "change": _change(before, after)},
                                nxt.observed_at, evidence_id=nxt.id))

            holding = [a for a in mine_at if node in a.nodes]
            nxt_at = min((a for a in holding if start < a.issued_at <= end
                          and a.id != action.own_attestation),
                         key=lambda a: (a.issued_at, a.id), default=None)
            if nxt_at is not None:
                prior_at = max((a for a in holding
                                if a.issued_at <= start or a.id == action.own_attestation),
                               key=lambda a: (a.issued_at, a.id), default=None)
                before_level = prior_at.level if prior_at else None
                add(OutcomeLink(action.id, {"kind": NODE_ATTESTATION, "node_id": node,
                                            "before": before_level, "after": nxt_at.level,
                                            "change": _rank_change(before_level, nxt_at.level)},
                                nxt_at.issued_at, attestation_id=nxt_at.id))

        own_scores = {c.criterion_score_id for c in action.criteria}
        for anchor in sorted(action.criteria, key=lambda c: c.criterion_id):
            nxt = min((e for e in mine_ev if e.criterion_id == anchor.criterion_id
                       and e.criterion_score_id not in own_scores
                       and start < e.observed_at <= end),
                      key=lambda e: (e.observed_at, e.id), default=None)
            if nxt is None:
                continue
            before, after = _number(anchor.before), _number(nxt.criterion_score)
            add(OutcomeLink(action.id, {"kind": CRITERION, "criterion_id": anchor.criterion_id,
                                        "criterion": anchor.key, "before": before,
                                        "after": after, "change": _change(before, after)},
                            nxt.observed_at, evidence_id=nxt.id))
    return links


# --- Postgres -------------------------------------------------------------------------------


def _uuid_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def action_nodes(output: dict[str, Any]) -> frozenset[str]:
    raw = output.get("node_ids")
    found = [output.get("node_id"), *(raw if isinstance(raw, list) else [])]
    return frozenset(n for n in (_uuid_text(v) for v in found) if n)


class PgOutcomeLinker:
    """Runs `link_outcomes` over the database inside one transaction holding a
    transaction-scoped advisory lock, so concurrent runs skip rather than double-write."""

    def __init__(self, pool: asyncpg.Pool, *, window: timedelta) -> None:
        self._pool = pool
        self._window = window

    async def run(self, now: datetime) -> int | None:
        """Rows written, or None when another run holds the lock.

        Actions created more than two windows before `now` are not rescanned.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)",
                                       ADVISORY_LOCK_KEY):
                log.info("outcome_linker_skipped", reason="another run holds the lock")
                return None
            actions = await self._actions(conn, now - 2 * self._window, now)
            if not actions:
                return 0
            persons = sorted({a.subject for a in actions})
            nodes = sorted({n for a in actions for n in a.nodes})
            criteria = sorted({c.criterion_id for a in actions for c in a.criteria})
            evidence = await self._evidence(conn, persons, nodes, criteria, now)
            attestations = await self._attestations(conn, persons, nodes, now)
            existing = await self._existing(conn, [a.id for a in actions])
            links = link_outcomes(actions, evidence, attestations, window=self._window,
                                  now=now, existing=existing)
            await conn.executemany(
                "INSERT INTO outcome_links (ai_action_id, evidence_id, attestation_id, delta,"
                " observed_at) VALUES ($1::uuid, $2::uuid, $3::uuid, $4::jsonb, $5)",
                [(link.ai_action_id, link.evidence_id, link.attestation_id,
                  json.dumps(link.delta, sort_keys=True), link.observed_at) for link in links],
            )
        log.info("outcome_linker_ran", actions=len(actions), links_written=len(links))
        return len(links)

    @staticmethod
    async def _actions(conn: asyncpg.Connection, since: datetime, now: datetime
                       ) -> list[LinkableAction]:
        rows = await conn.fetch(
            """
            SELECT a.id, a.subject_person, a.created_at, a.output, a.target_type, a.target_id,
                   coalesce(json_agg(json_build_object(
                       'criterion_id', cs.criterion_id, 'key', rc.key,
                       'score', coalesce(cs.final_score, cs.ai_score), 'id', cs.id))
                     FILTER (WHERE cs.id IS NOT NULL), '[]') AS criteria
            FROM ai_actions a
            LEFT JOIN criterion_scores cs ON cs.ai_action_id = a.id
            LEFT JOIN rubric_criteria rc ON rc.id = cs.criterion_id
            WHERE a.subject_person IS NOT NULL AND a.created_at > $1 AND a.created_at <= $2
            GROUP BY a.id
            """, since, now)
        actions = []
        for r in rows:
            output = _json(r["output"]) or {}
            criteria = tuple(
                CriterionAnchor(str(c["criterion_id"]), c["key"], c["score"], str(c["id"]))
                for c in _json(r["criteria"]))
            nodes = action_nodes(output if isinstance(output, dict) else {})
            if not nodes and not criteria:
                continue
            own = str(r["target_id"]) if r["target_type"] == "attestations" and r[
                "target_id"] else None
            actions.append(LinkableAction(str(r["id"]), str(r["subject_person"]),
                                          r["created_at"], nodes, criteria, own))
        return actions

    @staticmethod
    async def _evidence(conn: asyncpg.Connection, persons: list[str], nodes: list[str],
                        criteria: list[str], now: datetime) -> list[EvidenceObs]:
        rows = await conn.fetch(
            """
            SELECT e.id, e.person_id, e.node_id, e.score, e.observed_at, e.visibility,
                   cs.criterion_id, cs.id AS criterion_score_id,
                   coalesce(cs.final_score, cs.ai_score) AS criterion_score
            FROM evidence e
            LEFT JOIN criterion_scores cs ON cs.id = e.criterion_score_id
            WHERE e.person_id = ANY($1::uuid[]) AND e.observed_at <= $4
              AND (e.node_id = ANY($2::uuid[]) OR cs.criterion_id = ANY($3::uuid[]))
            """, persons, nodes, criteria, now)
        return [EvidenceObs(str(r["id"]), str(r["person_id"]), str(r["node_id"]), r["score"],
                            r["observed_at"],
                            str(r["criterion_id"]) if r["criterion_id"] else None,
                            str(r["criterion_score_id"]) if r["criterion_score_id"] else None,
                            r["criterion_score"], r["visibility"])
                for r in rows]

    @staticmethod
    async def _attestations(conn: asyncpg.Connection, persons: list[str], nodes: list[str],
                            now: datetime) -> list[AttestationObs]:
        if not nodes:
            return []
        rows = await conn.fetch(
            """
            SELECT id, person_id, node_id, node_set, level::text AS level, issued_at
            FROM attestations
            WHERE person_id = ANY($1::uuid[]) AND issued_at <= $3
              AND (node_id = ANY($2::uuid[]) OR node_set && $2::uuid[])
            """, persons, nodes, now)
        return [AttestationObs(
            str(r["id"]), str(r["person_id"]),
            frozenset(str(n) for n in [r["node_id"], *(r["node_set"] or [])] if n),
            r["level"], r["issued_at"]) for r in rows]

    @staticmethod
    async def _existing(conn: asyncpg.Connection, action_ids: list[str]
                        ) -> set[tuple[str, str, str]]:
        rows = await conn.fetch(
            "SELECT ai_action_id, delta FROM outcome_links WHERE ai_action_id = ANY($1::uuid[])",
            action_ids)
        return {link_key(str(r["ai_action_id"]), _json(r["delta"])) for r in rows}
