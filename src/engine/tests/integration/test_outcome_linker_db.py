"""Outcome linker against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Rows are dated in 2001 and the linker's `now`
is too, so its scan window holds only this test's actions.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from engine.auth.repository import create_pool
from engine.jobs.outcome_linker import ADVISORY_LOCK_KEY, PgOutcomeLinker

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")

T0 = datetime(2001, 3, 1, 9, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=20)
WINDOW = timedelta(days=14)


def at(days: float) -> datetime:
    return T0 + timedelta(days=days)


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    assert DSN is not None
    p = await create_pool(DSN)
    try:
        yield p
    finally:
        await p.close()


@dataclass
class Seed:
    student: uuid.UUID
    other: uuid.UUID
    concept: uuid.UUID
    criterion: uuid.UUID
    attest_action: uuid.UUID
    feedback_action: uuid.UUID
    other_action: uuid.UUID
    own_attestation: uuid.UUID
    next_attestation: uuid.UUID
    next_evidence: uuid.UUID
    revision_evidence: uuid.UUID


@pytest.fixture
async def seed(pool) -> AsyncIterator[Seed]:
    """An attestation action on a concept, then a criterion_feedback action scoring 'thesis' 2
    on the draft, a revision scored 3, and a mastery attestation. Evidence on both criterion
    scores is also evidence on the concept."""
    tag = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        student, other = [await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ('{student}', $1, $2)"
            " RETURNING id", f"{who} {tag}", f"{who}-{tag}@example.test")
            for who in ("student", "other")]
        course, concept, assignment = [await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ($1, $2) RETURNING id", kind, f"{kind} {tag}")
            for kind in ("course", "concept", "artifact")]
        rubric = await conn.fetchval(
            "INSERT INTO rubrics (title, criteria) VALUES ($1, '[]') RETURNING id", f"R {tag}")
        criterion = await conn.fetchval(
            "INSERT INTO rubric_criteria (rubric_id, key, description, levels)"
            " VALUES ($1, 'thesis', 'Thesis', '[]') RETURNING id", rubric)
        draft, revision = [await conn.fetchval(
            "INSERT INTO submissions (person_id, assignment_node, body_md, submitted_at,"
            " version, course_node) VALUES ($1, $2, 'essay', $3, $4, $5) RETURNING id",
            student, assignment, at(day), version, course) for day, version in ((0, 1), (3, 2))]

        async def action(action_type: str, subject: uuid.UUID, output: dict, day: float,
                         target: tuple[str, uuid.UUID] | None = None) -> uuid.UUID:
            return await conn.fetchval(
                "INSERT INTO ai_actions (agent, action_type, subject_person, course_node,"
                " target_type, target_id, output, created_at)"
                " VALUES ('tutor', $1, $2, $3, $4, $5, $6::jsonb, $7) RETURNING id",
                action_type, subject, course, target[0] if target else None,
                target[1] if target else None, json.dumps(output), at(day))

        async def attest(level: str, day: float) -> uuid.UUID:
            return await conn.fetchval(
                "INSERT INTO attestations (person_id, node_id, level, issued_at)"
                " VALUES ($1, $2, $3, $4) RETURNING id", student, concept, level, at(day))

        async def evidence(day: float, score: float, cs: uuid.UUID | None = None,
                           person: uuid.UUID | None = None,
                           visibility: str = "course") -> uuid.UUID:
            return await conn.fetchval(
                "INSERT INTO evidence (person_id, node_id, kind, score, source, observed_at,"
                " criterion_score_id, visibility)"
                " VALUES ($1, $2, 'mastery_check', $3, 'test', $4, $5, $6)"
                " RETURNING id", person or student, concept, score, at(day), cs, visibility)

        await evidence(-2, 0.4)
        # Private practice right before and after the action must not shape its link.
        await evidence(-1, 0.1, visibility="private")
        await evidence(0.3, 0.95, visibility="private")
        own = await attest("proficient", 0)
        attest_action = await action("attestation", student,
                                     {"node_id": str(concept), "level": "proficient"}, 0.0001,
                                     ("attestations", own))
        feedback_action = await action("criterion_feedback", student, {}, 0.5)
        other_action = await action("practice_item", other, {"node_id": str(concept)}, 1)
        draft_cs = await conn.fetchval(
            "INSERT INTO criterion_scores (submission_id, criterion_id, ai_score, ai_action_id)"
            " VALUES ($1, $2, 2, $3) RETURNING id", draft, criterion, feedback_action)
        revision_cs = await conn.fetchval(
            "INSERT INTO criterion_scores (submission_id, criterion_id, ai_score, final_score)"
            " VALUES ($1, $2, 2, 3) RETURNING id", revision, criterion)
        draft_ev = await evidence(0.6, 0.5, draft_cs)
        revision_ev = await evidence(3, 0.75, revision_cs)
        next_attestation = await attest("mastery", 4)
        await evidence(16, 0.9, person=other)
    ids = Seed(student, other, concept, criterion, attest_action, feedback_action, other_action,
               own, next_attestation, draft_ev, revision_ev)
    try:
        yield ids
    finally:
        async with pool.acquire() as conn:
            actions = [attest_action, feedback_action, other_action]
            await conn.execute("DELETE FROM outcome_links WHERE ai_action_id = ANY($1::uuid[])",
                               actions)
            await conn.execute("DELETE FROM evidence WHERE person_id = ANY($1::uuid[])",
                               [student, other])
            await conn.execute("DELETE FROM attestations WHERE person_id = $1", student)
            await conn.execute("DELETE FROM criterion_scores WHERE submission_id = ANY($1::uuid[])",
                               [draft, revision])
            await conn.execute("DELETE FROM ai_actions WHERE id = ANY($1::uuid[])", actions)
            await conn.execute("DELETE FROM submissions WHERE id = ANY($1::uuid[])",
                               [draft, revision])
            await conn.execute("DELETE FROM rubrics WHERE id = $1", rubric)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                               [course, concept, assignment])
            await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])",
                               [student, other])


async def _links(pool: asyncpg.Pool, seed: Seed) -> list[tuple]:
    rows = await pool.fetch(
        "SELECT ai_action_id, evidence_id, attestation_id, delta, observed_at FROM outcome_links"
        " WHERE ai_action_id = ANY($1::uuid[])"
        " ORDER BY ai_action_id, delta ->> 'kind'",
        [seed.attest_action, seed.feedback_action, seed.other_action])
    return [(r["ai_action_id"], r["evidence_id"], r["attestation_id"], json.loads(r["delta"]),
             r["observed_at"]) for r in rows]


async def test_links_next_evidence_attestation_and_criterion(pool, seed):
    written = await PgOutcomeLinker(pool, window=WINDOW).run(NOW)

    links = await _links(pool, seed)
    assert written == len(links) == 3
    by_kind = {(row[0], row[3]["kind"]): row for row in links}
    _, ev_id, _, delta, observed = by_kind[(seed.attest_action, "node_evidence")]
    assert ev_id == seed.next_evidence and observed == at(0.6)
    assert delta == {"kind": "node_evidence", "node_id": str(seed.concept), "before": 0.4,
                     "after": 0.5, "change": 0.1}
    _, _, att_id, delta, _ = by_kind[(seed.attest_action, "node_attestation")]
    assert att_id == seed.next_attestation
    assert delta == {"kind": "node_attestation", "node_id": str(seed.concept),
                     "before": "proficient", "after": "mastery", "change": 1}
    _, ev_id, _, delta, _ = by_kind[(seed.feedback_action, "criterion")]
    assert ev_id == seed.revision_evidence
    assert delta == {"kind": "criterion", "criterion_id": str(seed.criterion),
                     "criterion": "thesis", "before": 2.0, "after": 3.0, "change": 1.0}
    # The other student's only evidence is 15 days after their action: outside the window.
    assert not [row for row in links if row[0] == seed.other_action]


async def test_two_runs_write_the_same_rows_once(pool, seed):
    linker = PgOutcomeLinker(pool, window=WINDOW)
    await linker.run(NOW)
    first = await _links(pool, seed)

    assert await linker.run(NOW) == 0
    assert await linker.run(NOW + timedelta(days=1)) == 0
    assert await _links(pool, seed) == first


async def test_concurrent_runs_do_not_double_write(pool, seed):
    linker = PgOutcomeLinker(pool, window=WINDOW)
    results = await asyncio.gather(linker.run(NOW), linker.run(NOW))
    assert sorted(r for r in results if r is not None) in ([0, 3], [3])
    assert len(await _links(pool, seed)) == 3


async def test_run_skips_while_another_holds_the_lock(pool, seed):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", ADVISORY_LOCK_KEY)
        assert await PgOutcomeLinker(pool, window=WINDOW).run(NOW) is None
    assert await _links(pool, seed) == []


@pytest.mark.parametrize("enabled", ["true", "false"])
async def test_app_lifespan_runs_the_scheduler_unless_disabled(monkeypatch, enabled):
    from engine.app import create_app

    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("SCHEDULER_ENABLED", enabled)
    app = create_app()
    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        if enabled == "true":
            assert scheduler.running and scheduler.job_names == ["outcome_linker"]
        else:
            assert scheduler is None
    assert app.state.scheduler is None
