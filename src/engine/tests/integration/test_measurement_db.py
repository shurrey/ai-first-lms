"""PgMeasurementStore and the AI Review endpoints against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own course, rubric and
provenance rows and deletes them afterwards.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.auth.directory import PgScopeDirectory
from engine.auth.repository import create_pool
from engine.measurement import ActionQuery, LinkRecord, PgMeasurementStore, criterion_uuid
from engine.tests.auth_fakes import DEMO_PASSWORD, build_auth_world

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")

T0 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


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
    tag: str
    student: str
    faculty: str
    course: str
    program: str
    rubric: str
    thesis: str
    accepted: str
    edited: str
    undecided: str
    evidence: str


@pytest.fixture
async def seed(pool) -> AsyncIterator[Seed]:
    tag = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        student, faculty = [await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            [role], f"{role} {tag}", f"{role}-{tag}@example.test")
            for role in ("student", "faculty")]
        course = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', $1) RETURNING id", f"Meas {tag}")
        program = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('program', $1, $2::jsonb)"
            " RETURNING id", f"Prog {tag}", json.dumps({"program_lead_ids": [str(faculty)]}))
        await conn.execute("INSERT INTO edges (from_node, to_node, kind)"
                           " VALUES ($1, $2, 'part_of')", course, program)
        rubric = await conn.fetchval(
            "INSERT INTO rubrics (title, criteria) VALUES ($1, '[]'::jsonb) RETURNING id",
            f"R {tag}")
        thesis = await conn.fetchval(
            "INSERT INTO rubric_criteria (rubric_id, key, description, levels)"
            " VALUES ($1, 'thesis', 'Thesis', '[]'::jsonb) RETURNING id", rubric)
        evidence = await conn.fetchval(
            "INSERT INTO evidence (person_id, node_id, kind, score, source)"
            " VALUES ($1, $2, 'artifact_submission', 0.8, 'test') RETURNING id",
            student, course)

        async def action(hours: int, scores: dict) -> uuid.UUID:
            return await conn.fetchval(
                "INSERT INTO ai_actions (agent, action_type, subject_person, course_node,"
                " sources, output, created_at) VALUES ('grading_assistant', 'grade_draft',"
                " $1, $2, $3::jsonb, $4::jsonb, $5) RETURNING id",
                student, course, json.dumps([{"type": "rubric", "id": str(rubric)},
                                             {"type": "node", "id": str(course)}]),
                json.dumps({"rubric_id": str(rubric), "scores": scores}),
                T0 + timedelta(hours=hours))

        accepted = await action(1, {"thesis": 3, "evidence": 2})
        edited = await action(2, {"thesis": 4, "evidence": 2})
        undecided = await action(3, {"thesis": 1})
        await conn.execute(
            "INSERT INTO human_decisions (ai_action_id, decided_by, decision, decided_at)"
            " VALUES ($1, $2, 'accepted', $3)", accepted, faculty, T0 + timedelta(days=1))
        await conn.execute(
            "INSERT INTO human_decisions (ai_action_id, decided_by, decision, diff, decided_at)"
            " VALUES ($1, $2, 'edited', $3::jsonb, $4)", edited, faculty,
            json.dumps({"criteria": {"thesis": {"before": 4, "after": 2, "delta": -2},
                                     "evidence": {"before": 2, "after": 3, "delta": 1}}}),
            T0 + timedelta(days=1))
        await conn.execute(
            "INSERT INTO outcome_links (ai_action_id, evidence_id, delta, observed_at)"
            " VALUES ($1, $2, $3::jsonb, $4)", edited, evidence,
            json.dumps({"kind": "criterion", "before": 2, "after": 3, "change": 1}),
            T0 + timedelta(days=3))
    s = Seed(tag, *(str(v) for v in (student, faculty, course, program, rubric, thesis,
                                     accepted, edited, undecided, evidence)))
    try:
        yield s
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM ai_actions WHERE course_node = $1", course)
            await conn.execute("DELETE FROM evidence WHERE id = $1", evidence)
            await conn.execute("DELETE FROM rubrics WHERE id = $1", rubric)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                               [course, program])
            await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])",
                               [student, faculty])


async def test_find_actions_filters_and_pages(pool, seed):
    store = PgMeasurementStore(pool)
    end = T0 + timedelta(days=30)
    courses = frozenset({seed.course})
    every = await store.find_actions(ActionQuery(end=end, course_ids=courses))
    assert [a.id for a in every] == [seed.undecided, seed.edited, seed.accepted]
    assert every[0].sources[0] == {"type": "rubric", "id": seed.rubric}
    page = await store.find_actions(ActionQuery(end=end, course_ids=courses, limit=1,
                                                before=(every[0].created_at, every[0].id)))
    assert [a.id for a in page] == [seed.edited]
    none = await store.find_actions(ActionQuery(end=end, course_ids=courses, decision="none"))
    assert [a.id for a in none] == [seed.undecided]
    edited = await store.find_actions(ActionQuery(end=end, course_ids=courses,
                                                  decision="edited"))
    assert [a.id for a in edited] == [seed.edited]
    ranged = await store.find_actions(ActionQuery(end=T0 + timedelta(hours=2),
                                                  start=T0 + timedelta(hours=1),
                                                  course_ids=courses))
    assert [a.id for a in ranged] == [seed.accepted]
    assert await store.find_actions(ActionQuery(end=end, course_ids=frozenset())) == []
    assert await store.find_actions(ActionQuery(
        end=end, course_ids=courses, subject_ids=frozenset({seed.faculty}))) == []


async def test_details_titles_criteria_and_program(pool, seed):
    store = PgMeasurementStore(pool)
    decisions = await store.decisions_for([seed.accepted, seed.edited, seed.undecided])
    assert set(decisions) == {seed.accepted, seed.edited}
    assert decisions[seed.edited][0].decided_by_name == f"faculty {seed.tag}"
    links = await store.links_for([seed.edited])
    assert links[seed.edited][0].evidence_id == seed.evidence
    assert links[seed.edited][0].delta["change"] == 1
    assert await store.criterion_ids([(seed.rubric, "thesis"), (seed.rubric, "evidence")]) \
        == {(seed.rubric, "thesis"): seed.thesis}
    titles = await store.source_titles([("rubric", seed.rubric), ("node", seed.course),
                                        ("submission", seed.course)])
    assert titles == {("rubric", seed.rubric): f"R {seed.tag}",
                      ("node", seed.course): f"Meas {seed.tag}"}
    program = await store.program(seed.program)
    assert program is not None and program.course_ids == {seed.course}
    assert program.lead_ids == {seed.faculty}
    assert await store.program(seed.course) is None
    assert await store.get_action("not-a-uuid") is None


async def test_course_measurement_endpoint(pool, seed):
    world = build_auth_world()
    app = create_app(auth_service=world.service, scope_directory=PgScopeDirectory(pool))
    app.state.measurement_store = PgMeasurementStore(pool)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/auth/login", json={
            "username": world.people["admin"].email, "password": DEMO_PASSWORD})
        assert login.status_code == 200
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        resp = await client.get(f"/api/measurement/courses/{seed.course}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        rates = body["rates"][0]
        assert (rates["total"], rates["accepted"], rates["edited"], rates["undecided"]) == (
            3, 1, 1, 1)
        changes = {c["criterion_key"]: c for c in body["criterion_score_changes"]}
        assert changes["thesis"]["criterion_id"] == seed.thesis
        assert changes["thesis"]["mean_delta"] == -1.0
        assert changes["evidence"]["criterion_id"] == criterion_uuid(seed.rubric, "evidence")
        assert body["learning_delta_by_decision"]["edited"] == {"n": 1, "mean_delta": 1.0}

        rollup = await client.get("/api/measurement/rollup",
                                  params={"program_id": seed.program})
        assert rollup.status_code == 200
        assert [r["course"]["course_id"] for r in rollup.json()["per_course"]] == [seed.course]

        export = await client.get("/api/measurement/export", params={
            "course_id": seed.course, "format": "csv", "table": "outcome_links"})
        assert export.status_code == 200
        assert seed.evidence in export.text


async def test_learner_release_reads_committed_grades_and_released_feedback(pool, seed):
    async with pool.acquire() as conn:
        submission = await conn.fetchval(
            "INSERT INTO submissions (person_id, assignment_node, body_md)"
            " VALUES ($1, $2, 'essay') RETURNING id", uuid.UUID(seed.student),
            uuid.UUID(seed.course))
        committed, draft = [await conn.fetchval(
            "INSERT INTO grades (submission_id, scores, feedback, is_draft)"
            " VALUES ($1, '{}'::jsonb, '{}'::jsonb, $2) RETURNING id", submission, is_draft)
            for is_draft in (False, True)]
        await conn.execute("UPDATE ai_actions SET target_type = 'grades', target_id = $2"
                           " WHERE id = $1", uuid.UUID(seed.accepted), committed)
        await conn.execute("UPDATE ai_actions SET target_type = 'grades', target_id = $2"
                           " WHERE id = $1", uuid.UUID(seed.edited), draft)
        released, held = [await conn.fetchval(
            "INSERT INTO ai_actions (agent, action_type, subject_person, course_node, output)"
            " VALUES ('grading_assistant', 'criterion_feedback', $1, $2, '{}'::jsonb)"
            " RETURNING id", uuid.UUID(seed.student), uuid.UUID(seed.course))
            for _ in range(2)]
        await conn.executemany(
            "INSERT INTO criterion_scores (submission_id, criterion_id, ai_score, ai_action_id,"
            " released_at) VALUES ($1, $2, 3, $3, $4)",
            [(submission, uuid.UUID(seed.thesis), released, T0)])
        evidence_criterion = await conn.fetchval(
            "INSERT INTO rubric_criteria (rubric_id, key, description, levels)"
            " VALUES ($1, 'evidence', 'Evidence', '[]'::jsonb) RETURNING id",
            uuid.UUID(seed.rubric))
        await conn.execute(
            "INSERT INTO criterion_scores (submission_id, criterion_id, ai_score, ai_action_id)"
            " VALUES ($1, $2, 2, $3)", submission, evidence_criterion, held)
    try:
        store = PgMeasurementStore(pool)
        actions = [a for a in [await store.get_action(i) for i in (
            seed.accepted, seed.edited, seed.undecided, str(released), str(held))] if a]
        release = await store.learner_release(actions)
        assert release.committed_grades == {str(committed)}
        assert release.released_actions == {str(released)}
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM criterion_scores WHERE submission_id = $1",
                               submission)
            await conn.execute("UPDATE ai_actions SET target_id = NULL WHERE course_node = $1",
                               uuid.UUID(seed.course))
            await conn.execute("DELETE FROM grades WHERE submission_id = $1", submission)
            await conn.execute("DELETE FROM submissions WHERE id = $1", submission)


async def _submission(conn: asyncpg.Connection, seed: Seed, status: str) -> uuid.UUID:
    return await conn.fetchval(
        "INSERT INTO submissions (person_id, assignment_node, body_md, status, course_node)"
        " VALUES ($1, $2, 'essay', $3, $2) RETURNING id", uuid.UUID(seed.student),
        uuid.UUID(seed.course), status)


async def _drop_submissions(pool: asyncpg.Pool, seed: Seed, ids: list[uuid.UUID]) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM outcome_links WHERE ai_action_id IN"
                           " (SELECT id FROM ai_actions WHERE course_node = $1)",
                           uuid.UUID(seed.course))
        await conn.execute("DELETE FROM evidence WHERE person_id = $1 AND id <> $2",
                           uuid.UUID(seed.student), uuid.UUID(seed.evidence))
        await conn.execute("DELETE FROM criterion_scores WHERE submission_id = ANY($1)", ids)
        await conn.execute("DELETE FROM grades WHERE submission_id = ANY($1)", ids)
        await conn.execute("DELETE FROM ai_actions WHERE course_node = $1 AND target_id ="
                           " ANY($2)", uuid.UUID(seed.course), ids)
        await conn.execute("DELETE FROM submissions WHERE id = ANY($1)", ids)


async def test_find_actions_leaves_out_private_types_and_draft_feedback(pool, seed):
    async with pool.acquire() as conn:
        draft, final = await _submission(conn, seed, "draft"), await _submission(conn, seed,
                                                                                  "final")
        feedback = {}
        for name, sub in (("draft", draft), ("final", final)):
            feedback[name] = str(await conn.fetchval(
                "INSERT INTO ai_actions (agent, action_type, subject_person, course_node,"
                " target_type, target_id, output, created_at) VALUES ('feedback',"
                " 'criterion_feedback', $1, $2, 'submissions', $3, '{}'::jsonb, $4)"
                " RETURNING id", uuid.UUID(seed.student), uuid.UUID(seed.course), sub,
                T0 + timedelta(hours=5)))
        practice = str(await conn.fetchval(
            "INSERT INTO ai_actions (agent, action_type, subject_person, course_node, output,"
            " created_at) VALUES ('content_generator', 'practice_item', $1, $2, '{}'::jsonb,"
            " $3) RETURNING id", uuid.UUID(seed.student), uuid.UUID(seed.course),
            T0 + timedelta(hours=6)))
    try:
        store = PgMeasurementStore(pool)
        query = ActionQuery(end=T0 + timedelta(days=30), course_ids=frozenset({seed.course}))
        every = {a.id for a in await store.find_actions(query)}
        staff = {a.id for a in await store.find_actions(replace(
            query, exclude_types=frozenset({"practice_item"}),
            draft_feedback_courses=frozenset({seed.course})))}
        others = {a.id for a in await store.find_actions(replace(
            query, exclude_types=frozenset({"practice_item"}),
            draft_feedback_courses=frozenset()))}
        one = await store.find_actions(replace(query, ids=frozenset({practice})))

        assert {practice, feedback["draft"], feedback["final"]} <= every
        assert practice not in staff and {feedback["draft"], feedback["final"]} <= staff
        assert feedback["final"] in others and not {practice, feedback["draft"]} & others
        assert [a.id for a in one] == [practice]
    finally:
        await _drop_submissions(pool, seed, [draft, final])
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM ai_actions WHERE id = $1", uuid.UUID(practice))


async def test_learner_link_targets_are_released_or_committed_observations(pool, seed):
    async with pool.acquire() as conn:
        draft, final = await _submission(conn, seed, "draft"), await _submission(conn, seed,
                                                                                  "final")
        await conn.execute("INSERT INTO grades (submission_id, scores, feedback, is_draft)"
                           " VALUES ($1, '{}'::jsonb, '{}'::jsonb, false)", final)
        crit = {k: await conn.fetchval(
            "INSERT INTO rubric_criteria (rubric_id, key, description, levels)"
            " VALUES ($1, $2, $2, '[]'::jsonb) RETURNING id", uuid.UUID(seed.rubric), k)
            for k in ("released", "held", "graded", "ungraded")}

        async def score(sub: uuid.UUID, key: str, *, released: bool,
                        final_score: int | None = None) -> uuid.UUID:
            return await conn.fetchval(
                "INSERT INTO criterion_scores (submission_id, criterion_id, ai_score,"
                " final_score, released_at) VALUES ($1, $2, 3, $3, $4) RETURNING id",
                sub, crit[key], final_score, T0 if released else None)

        scores = {"released": await score(draft, "released", released=True),
                  "held": await score(draft, "held", released=False),
                  "graded": await score(final, "graded", released=False, final_score=4)}
        ungraded_final = await _submission(conn, seed, "final")
        scores["ungraded"] = await score(ungraded_final, "ungraded", released=False,
                                         final_score=4)

        async def evidence(visibility: str, score_id: uuid.UUID | None) -> str:
            return str(await conn.fetchval(
                "INSERT INTO evidence (person_id, node_id, kind, score, source, visibility,"
                " criterion_score_id) VALUES ($1, $2, 'artifact_submission', 0.5, 'test',"
                " $3, $4) RETURNING id", uuid.UUID(seed.student), uuid.UUID(seed.course),
                visibility, score_id))

        ev = {"plain": await evidence("course", None),
              "private": await evidence("private", None),
              "held": await evidence("course", scores["held"]),
              "released": await evidence("course", scores["released"])}
    try:
        store = PgMeasurementStore(pool)
        links = [LinkRecord(seed.edited, T0, evidence_id=e) for e in ev.values()]
        pairs = {"released": draft, "held": draft, "graded": final,
                 "ungraded": ungraded_final}
        links += [LinkRecord(seed.edited, T0, delta={"criterion_id": str(crit[k]),
                                                     "submission_id": str(sub)})
                  for k, sub in pairs.items()]

        targets = await store.learner_link_targets(links)

        assert targets.evidence == {ev["plain"]: None, ev["released"]: 3.0}
        assert targets.scores == {(str(draft), str(crit["released"])): 3.0,
                                  (str(final), str(crit["graded"])): 4.0}
    finally:
        await _drop_submissions(pool, seed, [draft, final, ungraded_final])
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM rubric_criteria WHERE id = ANY($1)",
                               list(crit.values()))
