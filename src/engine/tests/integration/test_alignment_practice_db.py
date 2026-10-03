"""Alignment decisions and practice attempts against Postgres: the proposal and practice
ai_actions rows and the human_decisions rows are real; the MCP tools are recorded fakes.

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own rows and deletes them.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

import engine.agents.runner as runner_mod
from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.auth.directory import PgScopeDirectory
from engine.auth.models import EnrollmentRecord
from engine.auth.repository import create_pool
from engine.formative.store import PgFormativeStore
from engine.provenance import (
    ALIGNMENT_TOOL,
    PgProvenanceStore,
    ProvenanceRecorder,
    ToolCallFacts,
)
from engine.tests.auth_fakes import CS101, DEMO_PASSWORD, AuthWorld, build_auth_world
from engine.tests.formative_fakes import RecordingTools

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")

LEVELS = [{"score": 1, "label": "Beginning", "descriptor": "Missing."},
          {"score": 2, "label": "Proficient", "descriptor": "Clear."}]


@dataclass
class Rig:
    pool: asyncpg.Pool
    world: AuthWorld
    tools: RecordingTools
    assignment: str
    app: object
    clients: list[AsyncClient] = field(default_factory=list)

    async def client(self, person: str) -> AsyncClient:
        """Signed in as `person`; closed when the test ends."""
        client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")
        self.clients.append(client)
        login = await client.post("/api/auth/login", json={
            "username": self.world.people[person].email, "password": DEMO_PASSWORD})
        assert login.status_code == 200, login.text
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        return client


@pytest.fixture
async def rig(monkeypatch) -> AsyncIterator[Rig]:
    assert DSN is not None
    pool = await create_pool(DSN)
    world = build_auth_world()
    people = [world.people[k] for k in ("faculty", "student", "noah")]
    tools = RecordingTools()
    monkeypatch.setattr(runner_mod, "_call_mcp_json", tools)
    async with pool.acquire() as conn:
        tag = uuid.uuid4().hex[:8]
        for p in people:  # sign-in uses the in-memory world; these rows satisfy foreign keys
            await conn.execute("INSERT INTO persons (id, roles, display_name, email)"
                               " VALUES ($1, $2, $3, $4)", uuid.UUID(p.id), list(p.roles),
                               p.display_name, f"{tag}-{p.email}")
        assignment = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('assessment_item', 'Essay',"
            " $1::jsonb) RETURNING id", json.dumps({"course_id": CS101.course_id}))
    app = create_app(auth_service=world.service, scope_directory=PgScopeDirectory(pool),
                     provenance=PgProvenanceStore(pool))
    app.state.formative_store = PgFormativeStore(pool)
    built = Rig(pool, world, tools, str(assignment), app)
    try:
        yield built
    finally:
        for client in built.clients:
            await client.aclose()
        ids = [uuid.UUID(p.id) for p in people]
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM human_decisions WHERE decided_by = ANY($1)", ids)
            await conn.execute("DELETE FROM ai_actions WHERE subject_person = ANY($1)"
                               " OR target_id = $2", ids, assignment)
            await conn.execute("DELETE FROM nodes WHERE id = $1", assignment)
            await conn.execute("DELETE FROM persons WHERE id = ANY($1)", ids)
        await pool.close()


async def test_alignment_decisions_are_recorded_on_the_stored_proposal(rig: Rig):
    recorder = ProvenanceRecorder(PgProvenanceStore(rig.pool))
    criteria = [{"key": k, "description": k, "levels": LEVELS, "outcome_nodes": []}
                for k in ("thesis", "evidence", "style")]
    await recorder.tool_succeeded(ToolCallFacts(
        agent="course_architect", tool=ALIGNMENT_TOOL, call_key=str(uuid.uuid4()),
        requester_id=rig.world.people["faculty"].id,
        args={"assignment_node": rig.assignment}, proposed={"assignment_node": rig.assignment},
        result={"assignment_node": rig.assignment, "proposal": {"criteria": criteria}}))
    rig.tools.replies["assessments.apply_alignment"] = {
        "rubric_id": str(uuid.uuid4()), "criterion_ids": [], "created": 2, "updated": 0}

    faculty = await rig.client("faculty")
    resp = await faculty.post(
        f"/api/assignments/{rig.assignment}/alignment/decisions",
        json={"decisions": [{"key": "thesis", "decision": "accept"},
                            {"key": "evidence", "decision": "edit",
                             "criterion": {**criteria[1], "description": "Cites sources"}},
                            {"key": "style", "decision": "reject"}]})

    assert resp.status_code == 201, resp.text
    async with rig.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT a.id AS action, a.output->>'tool' AS tool, d.decision,"
            " d.diff->>'criterion_key' AS key FROM human_decisions d"
            " JOIN ai_actions a ON a.id = d.ai_action_id"
            " WHERE a.target_type = 'nodes' AND a.target_id = $1", uuid.UUID(rig.assignment))
    assert sorted((r["decision"], r["key"]) for r in rows) == [
        ("accepted", "thesis"), ("edited", "evidence"), ("rejected", "style")]
    assert {(str(r["action"]), r["tool"]) for r in rows} == {
        (resp.json()["ai_action_id"], ALIGNMENT_TOOL)}


async def test_only_the_learner_attempts_a_stored_practice_set(rig: Rig):
    student = rig.world.people["student"].id
    async with rig.pool.acquire() as conn:
        practice = str(await conn.fetchval(
            "INSERT INTO ai_actions (agent, action_type, subject_person, output) VALUES"
            " ('content_generator', 'practice_item', $1, '{}'::jsonb) RETURNING id",
            uuid.UUID(student)))
    question = str(uuid.uuid4())
    rig.tools.replies["assessments.record_practice_attempt"] = {
        "evidence_ids": [], "items": [{"question_id": question, "correct": False,
                                       "answer_key": {"correct": "B"}}]}
    body = {"answers": [{"question_id": question, "answer": "A"}]}

    emma, noah = await rig.client("student"), await rig.client("noah")
    own = await emma.post(f"/api/practice/{practice}/attempts", json=body)
    other = await noah.post(f"/api/practice/{practice}/attempts", json=body)

    assert own.status_code == 201, own.text
    assert (own.json()["correct"], own.json()["total"]) == (0, 1)
    assert other.status_code == 404
    assert rig.tools.calls_to("assessments.record_practice_attempt") == [{
        "person_id": student, "practice_set_id": practice,
        "answers": [{"question_id": question, "answer": "A"}]}]


# --- end to end with the assessments server's handlers ---------------------------------------


@dataclass
class Course:
    id: str
    outcome: str
    assignment: str


@pytest.fixture
async def course(rig: Rig, monkeypatch) -> AsyncIterator[Course]:
    """A course with one outcome and one assignment, taught by the rig's faculty, with MCP
    calls running in-process against the assessments server's tool handlers."""
    from data_mcp.mcp_servers.assessments.tools import get_tools

    handlers = {t.name: t.handler for t in get_tools(rig.pool)}

    async def call(tool: str, args: dict[str, Any]) -> Any:
        return json.loads(json.dumps(await handlers[tool](args), default=str))

    monkeypatch.setattr(runner_mod, "_call_mcp_json", call)
    faculty = rig.world.people["faculty"].id
    async with rig.pool.acquire() as conn:
        course_id = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', 'E2E course') RETURNING id")
        meta = json.dumps({"course_id": str(course_id)})
        outcome = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('outcome', 'Uses evidence',"
            " $1::jsonb) RETURNING id", meta)
        assignment = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('assessment_item', 'E2E essay',"
            " $1::jsonb) RETURNING id", meta)
        await conn.execute("INSERT INTO enrollments (person_id, course_node, role)"
                           " VALUES ($1, $2, 'faculty')", uuid.UUID(faculty), course_id)
    rig.world.repo.enrollments[faculty].append(
        EnrollmentRecord(str(course_id), "e2e", "E2E course", "faculty"))
    try:
        yield Course(str(course_id), str(outcome), str(assignment))
    finally:
        async with rig.pool.acquire() as conn:
            await conn.execute("DELETE FROM evidence WHERE node_id = $1", outcome)
            await conn.execute("DELETE FROM questions WHERE bank_id IN (SELECT id FROM"
                               " question_banks WHERE course_node = $1)", course_id)
            await conn.execute("DELETE FROM question_banks WHERE course_node = $1", course_id)
            await conn.execute("DELETE FROM human_decisions WHERE ai_action_id IN (SELECT id"
                               " FROM ai_actions WHERE target_id = $1)", assignment)
            await conn.execute("DELETE FROM ai_actions WHERE target_id = $1"
                               " OR course_node = $2", assignment, course_id)
            rubric = await conn.fetchval("SELECT (metadata->>'rubric_id')::uuid FROM nodes"
                                         " WHERE id = $1", assignment)
            await conn.execute("DELETE FROM edges WHERE from_node = $1 OR to_node = $1"
                               " OR from_node = $2 OR to_node = $2", assignment, outcome)
            await conn.execute("DELETE FROM enrollments WHERE course_node = $1", course_id)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1)",
                               [assignment, outcome, course_id])
            if rubric is not None:
                await conn.execute("DELETE FROM rubrics WHERE id = $1", rubric)


async def test_accepted_alignment_sets_the_criteria_outcomes(rig: Rig, course: Course):
    criteria = [{"key": k, "description": f"{k} description", "levels": LEVELS,
                 "outcome_nodes": [course.outcome]}
                for k in ("thesis", "evidence", "organization")]
    proposed = await runner_mod._call_mcp_json("assessments.propose_alignment", {
        "assignment_node": course.assignment, "criteria": criteria})
    assert proposed.get("proposal"), proposed
    await ProvenanceRecorder(PgProvenanceStore(rig.pool)).tool_succeeded(ToolCallFacts(
        agent="course_architect", tool=ALIGNMENT_TOOL, call_key=str(uuid.uuid4()),
        requester_id=rig.world.people["faculty"].id,
        args={"assignment_node": course.assignment},
        proposed={"assignment_node": course.assignment}, result=proposed))

    faculty = await rig.client("faculty")
    resp = await faculty.post(f"/api/assignments/{course.assignment}/alignment/decisions",
                              json={"decisions": [
                                  {"key": "thesis", "decision": "accept"},
                                  {"key": "evidence", "decision": "edit", "criterion": {
                                      **criteria[1], "description": "Cites two sources"}},
                                  {"key": "organization", "decision": "reject"}]})

    assert resp.status_code == 201, resp.text
    async with rig.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, description, outcome_nodes FROM rubric_criteria"
            " WHERE rubric_id = $1 ORDER BY key", uuid.UUID(resp.json()["rubric_id"]))
        decided = await conn.fetch(
            "SELECT decision FROM human_decisions WHERE ai_action_id = $1",
            uuid.UUID(resp.json()["ai_action_id"]))
    assert [(r["key"], r["description"], [str(n) for n in r["outcome_nodes"]])
            for r in rows] == [("evidence", "Cites two sources", [course.outcome]),
                               ("thesis", "thesis description", [course.outcome])]
    assert sorted(r["decision"] for r in decided) == ["accepted", "edited", "rejected"]


async def test_a_practice_attempt_is_marked_and_kept_private(rig: Rig, course: Course):
    student = rig.world.people["student"].id
    async with rig.pool.acquire() as conn:
        practice = await conn.fetchval(
            "INSERT INTO ai_actions (agent, action_type, subject_person, course_node, output)"
            " VALUES ('content_generator', 'practice_item', $1, $2, '{}'::jsonb) RETURNING id",
            uuid.UUID(student), uuid.UUID(course.id))
        bank = await conn.fetchval(
            "INSERT INTO question_banks (course_node, title, metadata) VALUES ($1, 'Practice',"
            " '{\"kind\": \"practice\"}'::jsonb) RETURNING id", uuid.UUID(course.id))
        question = await conn.fetchval(
            "INSERT INTO questions (bank_id, type, stem, answer_key, aligned_nodes, metadata)"
            " VALUES ($1, 'mcq', 'Which cites a source?', $2::jsonb, $3, $4::jsonb)"
            " RETURNING id", bank, json.dumps({"correct": "B", "explanation": "B names it."}),
            [uuid.UUID(course.outcome)],
            json.dumps({"practice_set_id": str(practice), "student_id": student}))

    emma = await rig.client("student")
    resp = await emma.post(f"/api/practice/{practice}/attempts",
                           json={"answers": [{"question_id": str(question), "answer": "a"}]})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["results"] == [{"question_id": str(question), "correct": False,
                                "expected": "B", "feedback": "B names it."}]
    async with rig.pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, visibility, source FROM evidence"
                                " WHERE person_id = $1 AND node_id = $2",
                                uuid.UUID(student), uuid.UUID(course.outcome))
    assert [(str(r["id"]), r["visibility"], r["source"]) for r in rows] == [
        (body["attempt_id"], "private", "practice")]
