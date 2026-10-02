"""Seeded provenance history (spec §6.3, §6.6) so the AI Review tab has data on a fresh seed.

Reads the grades, attestations, content and microcredentials the course seed wrote and
records ai_actions / human_decisions / outcome_links consistent with them: draft grades
are undecided grade_draft actions, committed grades carry accepted/edited/rejected decisions.
"""
from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Any

import asyncpg

PROVENANCE_COURSES = ("cs101", "eng102")

SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"

CRITERION_MAX = {"correctness": 40, "style": 30, "completeness": 30}

# Which criteria instructors edit most, per course; drives the "edited most" view.
EDIT_WEIGHTS = {
    "cs101": {"correctness": 0.3, "style": 0.5, "completeness": 0.2},
    "eng102": {"correctness": 0.2, "style": 0.55, "completeness": 0.25},
}

GRADE_DECISION_WEIGHTS = (("accepted", 0.55), ("edited", 0.35), ("rejected", 0.10))
OUTCOME_LINK_SHARE = 0.6

REJECT_REASONS = (
    "Draft misread the assignment requirements.",
    "Scores do not reflect the rubric descriptors.",
    "Feedback addressed the wrong submission version.",
)
EDIT_REASONS = (
    "Adjusted to match the rubric level descriptors.",
    "Draft was too generous on this criterion.",
    "Draft was too harsh on this criterion.",
    None,
)


def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _pick(rng: random.Random, weighted: tuple[tuple[str, float], ...]) -> str:
    return rng.choices([k for k, _ in weighted], weights=[w for _, w in weighted])[0]


def _prompt_sha(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class _Writer:
    """Buffers rows so each table is written with one executemany."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.actions: list[tuple] = []
        self.decisions: list[tuple] = []
        self.links: list[tuple] = []

    def action(
        self, *, agent: str, action_type: str, subject: uuid.UUID | None, course: uuid.UUID,
        target_type: str | None, target_id: uuid.UUID | None, sources: list[dict],
        model: str, output: dict, created_at: datetime,
    ) -> uuid.UUID:
        aid = _uuid(self.rng)
        self.actions.append((
            aid, agent, action_type, subject, course, target_type, target_id,
            # Hashes only stable inputs: attestation and evidence ids are DB defaults.
            json.dumps(sources), model, _prompt_sha(agent, action_type, subject, sources),
            json.dumps(output), created_at,
        ))
        return aid

    def decision(
        self, action_id: uuid.UUID, decided_by: uuid.UUID, decision: str,
        decided_at: datetime, diff: dict | None = None, reason: str | None = None,
    ) -> None:
        self.decisions.append((
            _uuid(self.rng), action_id, decided_by, decision,
            json.dumps(diff) if diff is not None else None, reason, decided_at,
        ))

    def link(
        self, action_id: uuid.UUID, observed_at: datetime, delta: dict,
        evidence_id: uuid.UUID | None = None, attestation_id: uuid.UUID | None = None,
    ) -> None:
        self.links.append((action_id, evidence_id, attestation_id, json.dumps(delta), observed_at))

    async def flush(self, conn: asyncpg.Connection) -> None:
        await conn.executemany(
            """INSERT INTO ai_actions (id, agent, action_type, subject_person, course_node,
                   target_type, target_id, sources, model, prompt_sha256, output, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            self.actions,
        )
        await conn.executemany(
            """INSERT INTO human_decisions (id, ai_action_id, decided_by, decision, diff,
                   reason, decided_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            self.decisions,
        )
        await conn.executemany(
            """INSERT INTO outcome_links (ai_action_id, evidence_id, attestation_id, delta,
                   observed_at)
               VALUES ($1, $2, $3, $4, $5)""",
            self.links,
        )


async def seed_provenance(
    conn: asyncpg.Connection, rng: random.Random, course_ids: dict[str, str],
    instructor_emails: dict[str, str],
) -> dict[str, int]:
    """Write provenance rows for PROVENANCE_COURSES. Deterministic for a given rng state.

    instructor_emails maps course slug to the faculty member who reviews AI output there.
    """
    w = _Writer(rng)
    for slug in PROVENANCE_COURSES:
        course_id = uuid.UUID(course_ids[slug])
        faculty = await conn.fetchval(
            "SELECT id FROM persons WHERE email = $1", instructor_emails[slug],
        )
        await _grade_drafts(conn, w, slug, course_id, faculty)
        await _generations(conn, w, course_id, faculty)
        await _attestations(conn, w, course_id, faculty)
        await _recommendations(conn, w, course_id, faculty)
        await _profile_updates(conn, w, course_id)
    await w.flush(conn)
    return {
        "ai_actions": len(w.actions),
        "human_decisions": len(w.decisions),
        "outcome_links": len(w.links),
    }


async def _grade_drafts(
    conn: asyncpg.Connection, w: _Writer, slug: str, course_id: uuid.UUID,
    faculty: uuid.UUID,
) -> None:
    grades = await conn.fetch(
        """SELECT g.id, g.submission_id, g.rubric_id, g.scores, g.feedback, g.graded_by,
                  g.is_draft, g.committed_at, s.person_id, s.assignment_node, s.submitted_at
           FROM grades g
           JOIN submissions s ON s.id = g.submission_id
           JOIN nodes n ON n.id = s.assignment_node
           WHERE n.metadata->>'course_id' = $1
           ORDER BY s.submitted_at, g.id""",
        str(course_id),
    )
    # Learning deltas may only cite course-visible evidence (spec §12.5).
    evidence = {
        (r["person_id"], r["node_id"]): r["id"]
        for r in await conn.fetch(
            """SELECT ev.id, ev.person_id, ev.node_id FROM evidence ev
               JOIN nodes n ON n.id = ev.node_id
               WHERE ev.kind = 'artifact_submission' AND ev.visibility <> 'private'
                 AND n.metadata->>'course_id' = $1""",
            str(course_id),
        )
    }
    committed_by_student: dict[uuid.UUID, list[asyncpg.Record]] = {}
    for g in grades:
        if not g["is_draft"]:
            committed_by_student.setdefault(g["person_id"], []).append(g)

    weights = tuple(EDIT_WEIGHTS[slug].items())
    for g in grades:
        final = _json(g["scores"])
        created_at = g["submitted_at"] + timedelta(days=1, hours=w.rng.randint(1, 20))
        decision = None if g["is_draft"] else _pick(w.rng, GRADE_DECISION_WEIGHTS)
        ai_scores, changed = _ai_scores(w.rng, final, decision, weights)
        aid = w.action(
            agent="grading_assistant", action_type="grade_draft", subject=g["person_id"],
            course=course_id, target_type="grades", target_id=g["id"],
            sources=[
                {"type": "submission", "id": str(g["submission_id"]), "version": 1},
                {"type": "rubric", "id": str(g["rubric_id"]), "version": None},
                {"type": "node", "id": str(g["assignment_node"]), "version": None},
            ],
            model=SONNET,
            output={
                "scores": ai_scores,
                "total": sum(ai_scores.values()),
                "feedback": {k: f"Score: {v}/{CRITERION_MAX[k]}" for k, v in ai_scores.items()},
            },
            created_at=created_at,
        )
        if decision is None:
            continue
        # Seeded commit dates can precede the submission; keep decisions after the draft.
        decided_at = max(g["committed_at"], created_at + timedelta(days=2))
        diff = {
            "criteria": [
                {
                    "key": k, "rubric_id": str(g["rubric_id"]),
                    "ai_score": ai_scores[k], "final_score": final[k],
                    "delta": final[k] - ai_scores[k],
                }
                for k in changed
            ],
            "feedback_edit_distance": (
                0 if decision == "accepted"
                else w.rng.randint(15, 120) if decision == "edited"
                else w.rng.randint(180, 400)
            ),
        }
        reason = (
            w.rng.choice(REJECT_REASONS) if decision == "rejected"
            else w.rng.choice(EDIT_REASONS) if decision == "edited" else None
        )
        w.decision(aid, g["graded_by"] or faculty, decision, decided_at, diff, reason)
        _grade_outcome(w, aid, g, final, changed, decided_at, committed_by_student, evidence)


def _ai_scores(
    rng: random.Random, final: dict[str, int], decision: str | None,
    weights: tuple[tuple[str, float], ...],
) -> tuple[dict[str, int], list[str]]:
    """Return the AI-drafted scores and the criteria the instructor changed."""
    if decision in (None, "accepted"):
        return dict(final), []
    if decision == "rejected":
        changed = list(CRITERION_MAX)
    else:
        first = _pick(rng, weights)
        changed = [first]
        if rng.random() < 0.3:
            changed.append(_pick(rng, tuple((k, v) for k, v in weights if k != first)))
    ai = dict(final)
    for k in changed:
        spread = 12 if decision == "rejected" else 6
        candidates = [
            s for s in range(final[k] - spread, final[k] + spread + 1)
            if 0 <= s <= CRITERION_MAX[k] and s != final[k]
        ]
        # Drafts lean generous, so instructor edits mostly lower the score.
        generous = [s for s in candidates if s > final[k]]
        ai[k] = rng.choice(generous if generous and rng.random() < 0.7 else candidates)
    return ai, sorted(changed)


def _grade_outcome(
    w: _Writer, aid: uuid.UUID, g: asyncpg.Record, final: dict[str, int], changed: list[str],
    decided_at: datetime, committed_by_student: dict[uuid.UUID, list[asyncpg.Record]],
    evidence: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID],
) -> None:
    """Link to the student's next committed submission after the decision, for a subset."""
    if w.rng.random() >= OUTCOME_LINK_SHARE:
        return
    later = [
        n for n in committed_by_student.get(g["person_id"], [])
        if n["submitted_at"] > decided_at and n["id"] != g["id"]
    ]
    if not later:
        return
    nxt = later[0]
    ev_id = evidence.get((nxt["person_id"], nxt["assignment_node"]))
    if ev_id is None:
        return
    criterion = changed[0] if changed else min(final, key=lambda k: final[k] / CRITERION_MAX[k])
    after = _json(nxt["scores"])[criterion]
    w.link(
        aid, nxt["submitted_at"],
        {"criterion": criterion, "before": final[criterion], "after": after,
         "max": CRITERION_MAX[criterion]},
        evidence_id=ev_id,
    )


async def _generations(
    conn: asyncpg.Connection, w: _Writer, course_id: uuid.UUID, faculty: uuid.UUID,
) -> None:
    items = await conn.fetch(
        """SELECT ci.id, ci.node_id, ci.kind, ci.title, n.metadata->>'order' AS ord
           FROM content_items ci JOIN nodes n ON n.id = ci.node_id
           WHERE n.kind = 'module' AND n.metadata->>'course_id' = $1
             AND ci.kind IN ('document', 'reading', 'slide_deck')
           ORDER BY ci.id""",
        str(course_id),
    )
    weighted = (("accepted", 0.45), ("edited", 0.35), ("rejected", 0.1), ("undecided", 0.1))
    base = datetime.fromisoformat("2026-08-10T15:00:00+00:00")
    for item in w.rng.sample(list(items), min(12, len(items))):
        decision = _pick(w.rng, weighted)
        created_at = base + timedelta(days=int(item["ord"]) * 3, hours=w.rng.randint(0, 8))
        published = decision in ("accepted", "edited")
        aid = w.action(
            agent="content_generator", action_type="generation", subject=None, course=course_id,
            target_type="content_items" if published else "nodes",
            target_id=item["id"] if published else item["node_id"],
            sources=[{"type": "node", "id": str(item["node_id"]), "version": None}],
            model=HAIKU,
            output={"kind": item["kind"], "title": item["title"],
                    "chars": w.rng.randint(1800, 6000)},
            created_at=created_at,
        )
        if decision == "undecided":
            continue
        diff = None
        if decision == "edited":
            diff = {"text": {"chars_added": w.rng.randint(40, 600),
                             "chars_removed": w.rng.randint(20, 400)}}
        reason = "Off-level for this module." if decision == "rejected" else None
        w.decision(aid, faculty, decision, created_at + timedelta(days=1), diff, reason)


async def _attestations(
    conn: asyncpg.Connection, w: _Writer, course_id: uuid.UUID, faculty: uuid.UUID,
) -> None:
    rows = await conn.fetch(
        """SELECT a.id, a.person_id, a.node_id, a.level::text AS level, n.title
           FROM attestations a JOIN nodes n ON n.id = a.node_id
           WHERE n.metadata->>'course_id' = $1 AND a.level IN ('emerging', 'proficient')
           ORDER BY a.person_id, a.node_id, a.level""",
        str(course_id),
    )
    levels = ["emerging", "proficient", "mastery"]
    weighted = (("accepted", 0.55), ("overridden", 0.25), ("undecided", 0.2))
    base = datetime.fromisoformat("2026-09-08T14:00:00+00:00")
    for a in w.rng.sample(list(rows), min(14, len(rows))):
        decision = _pick(w.rng, weighted)
        ai_level = a["level"]
        if decision == "overridden":
            ai_level = w.rng.choice([lv for lv in levels if lv != a["level"]])
        created_at = base + timedelta(days=w.rng.randint(0, 20), hours=w.rng.randint(0, 9))
        aid = w.action(
            agent="tutor", action_type="attestation", subject=a["person_id"], course=course_id,
            target_type="attestations", target_id=a["id"],
            sources=[{"type": "node", "id": str(a["node_id"]), "version": None}],
            model=SONNET,
            output={"node_id": str(a["node_id"]), "concept": a["title"], "level": ai_level},
            created_at=created_at,
        )
        if decision == "undecided":
            continue
        overridden = decision == "overridden"
        diff = {"level": {"ai": ai_level, "final": a["level"]}} if overridden else None
        reason = "Tutor evidence was a single exchange." if overridden else None
        w.decision(aid, faculty, decision, created_at + timedelta(days=2), diff, reason)


async def _recommendations(
    conn: asyncpg.Connection, w: _Writer, course_id: uuid.UUID, faculty: uuid.UUID,
) -> None:
    mc = await conn.fetchrow(
        """SELECT id, title FROM nodes WHERE kind = 'microcredential'
             AND metadata->>'course_id' = $1 ORDER BY title LIMIT 1""",
        str(course_id),
    )
    if mc is None:
        return
    students = await conn.fetch(
        """SELECT a.person_id, count(*) AS n FROM attestations a JOIN nodes n ON n.id = a.node_id
           WHERE n.metadata->>'course_id' = $1 AND a.level = 'mastery'
           GROUP BY a.person_id ORDER BY a.person_id""",
        str(course_id),
    )
    weighted = (("accepted", 0.6), ("rejected", 0.15), ("undecided", 0.25))
    base = datetime.fromisoformat("2026-09-28T16:00:00+00:00")
    for s in students[:8]:
        decision = _pick(w.rng, weighted)
        created_at = base + timedelta(days=w.rng.randint(0, 6), hours=w.rng.randint(0, 6))
        aid = w.action(
            agent="learning_analyst", action_type="recommendation", subject=s["person_id"],
            course=course_id, target_type="nodes", target_id=mc["id"],
            sources=[{"type": "node", "id": str(mc["id"]), "version": None}],
            model=SONNET,
            output={"microcredential_id": str(mc["id"]), "title": mc["title"],
                    "eligible": True, "mastery_attestations": s["n"]},
            created_at=created_at,
        )
        if decision == "undecided":
            continue
        reason = "Wants one more applied project first." if decision == "rejected" else None
        w.decision(aid, faculty, decision, created_at + timedelta(days=1), None, reason)


async def _profile_updates(
    conn: asyncpg.Connection, w: _Writer, course_id: uuid.UUID,
) -> None:
    students = await conn.fetch(
        """SELECT e.person_id FROM enrollments e WHERE e.course_node = $1 AND e.role = 'student'
           ORDER BY e.person_id""",
        course_id,
    )
    concepts = await conn.fetch(
        """SELECT id, title FROM nodes WHERE kind = 'concept' AND metadata->>'course_id' = $1
           ORDER BY id""",
        str(course_id),
    )
    if not concepts:
        return
    base = datetime.fromisoformat("2026-09-21T09:00:00+00:00")
    for s in w.rng.sample(list(students), min(8, len(students))):
        strengths = w.rng.sample(list(concepts), 2)
        focus = w.rng.sample([c for c in concepts if c not in strengths], 2)
        created_at = base + timedelta(days=w.rng.randint(0, 7), hours=w.rng.randint(0, 10))
        aid = w.action(
            agent="learning_analyst", action_type="profile_update", subject=s["person_id"],
            course=course_id, target_type=None, target_id=None,
            sources=[{"type": "node", "id": str(c["id"]), "version": None}
                     for c in strengths + focus],
            model=SONNET,
            output={"strengths": [c["title"] for c in strengths],
                    "focus": [c["title"] for c in focus]},
            created_at=created_at,
        )
        if w.rng.random() < 0.25:
            w.decision(aid, s["person_id"], "disputed", created_at + timedelta(days=3), None,
                       "I have practised this since the last quiz.")
