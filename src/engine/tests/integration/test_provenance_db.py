"""Provenance write points against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own rows and deletes
them afterwards. MCP servers are faked; ai_actions and human_decisions are real.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.auth.models import EnrollmentRecord
from engine.auth.repository import create_pool
from engine.guardrails.approval import ApprovalDecision, ApprovalGate
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.provenance import (
    AiActionRow,
    PgProvenanceStore,
    ProvenanceRecorder,
    ProvenanceTrail,
)
from engine.tests.auth_fakes import (
    DEMO_PASSWORD,
    AuthWorld,
    auth_context,
    build_auth_world,
)
from engine.tests.object_fakes import InMemoryObjectDirectory

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")


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
    student: str
    faculty: str
    course: str
    micro: str
    session: str
    turn: str
    pending: str
    submission: str


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


@pytest.fixture
async def seed(pool, world) -> AsyncIterator[Seed]:
    """Persons rows carry the fake auth world's student and faculty ids."""
    tag = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        student, faculty = [await conn.fetchval(
            "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)"
            " RETURNING id", uuid.UUID(world.people[role].id), [role], f"{role} {tag}",
            f"{role}-{tag}@example.test")
            for role in ("student", "faculty")]
        course = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', $1) RETURNING id", f"C {tag}")
        micro = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('microcredential', $1) RETURNING id",
            f"M {tag}")
        session = await conn.fetchval(
            "INSERT INTO sessions (person_id, persona, course_node) VALUES ($1, 'faculty', $2)"
            " RETURNING id", faculty, course)
        turn = await conn.fetchval(
            "INSERT INTO turns (session_id, user_message) VALUES ($1, 'grade') RETURNING id",
            session)
        pending = await conn.fetchval(
            "INSERT INTO pending_credentials (person_id, microcredential_id, course_id)"
            " VALUES ($1, $2, $3) RETURNING id", student, micro, course)
    ids = Seed(*(str(v) for v in (student, faculty, course, micro, session, turn, pending,
                                  uuid.uuid4())))
    try:
        yield ids
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ai_actions WHERE session_id = $1 OR subject_person = $2"
                " OR course_node = $3", session, student, course)
            await conn.execute("DELETE FROM pending_credentials WHERE id = $1", pending)
            await conn.execute("DELETE FROM sessions WHERE id = $1", session)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])", [course, micro])
            await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])",
                               [student, faculty])


class Mcp:
    def __init__(self, seed: Seed) -> None:
        self.seed = seed
        self.grades = [str(uuid.uuid4()), str(uuid.uuid4())]

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        if tool == "assessments.draft_grade":
            return json.dumps({"grade_id": self.grades.pop(0)})
        if tool == "assessments.get_submission":
            return json.dumps({"id": args["submission_id"], "person_id": self.seed.student})
        if tool == "assessments.commit_grade":
            return json.dumps({"committed": True, "committed_at": "2026-10-02T12:00:00Z"})
        if tool == "roster.get":
            return json.dumps({"id": args["person_id"], "display_name": "Student"})
        return json.dumps({"ok": True})


async def test_grading_flow_records_the_instructors_criterion_change(pool, seed, world):
    """§6.6 acceptance: the instructor has thesis redrafted from 2 to 3, then commits."""
    course = EnrollmentRecord(seed.course, "c", "C", "student")
    world.repo.enrollments[seed.student].append(course)
    world.repo.enrollments[seed.faculty].append(replace(course, role="faculty"))
    store = PgProvenanceStore(pool)
    gate = ApprovalGate()
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    objects = InMemoryObjectDirectory(submissions={seed.submission: seed.course})
    gateway = ToolGateway(Mcp(seed), directory=world.directory, objects=objects,
                          approvals=gate, approval_timeout=5.0,
                          provenance=ProvenanceRecorder(store))
    ctx = GatewayContext(auth=auth_context(world, "faculty"), session_id=seed.session,
                         turn_id=seed.turn, step_id="s1", course_id=seed.course, emit=emit,
                         provenance=ProvenanceTrail(model="claude-test",
                                                    prompt_sha256="cd" * 32))

    def draft(thesis: int) -> dict[str, Any]:
        return {"submission_id": seed.submission, "scores": {"thesis": thesis, "evidence": 3},
                "feedback": {"thesis": "Clear.", "evidence": "Good."}, "holistic_md": "Fine.",
                "graded_by": seed.faculty}

    await gateway.invoke(ctx, "grading_assistant", "assessments.draft_grade", draft(2),
                         call_id="tu1")
    second = await gateway.invoke(ctx, "grading_assistant", "assessments.draft_grade",
                                  draft(3), call_id="tu2")
    grade_id = json.loads(second.text)["grade_id"]
    commit = asyncio.create_task(gateway.invoke(
        ctx, "grading_assistant", "assessments.commit_grade", {"grade_id": grade_id},
        call_id="tu3"))
    for _ in range(100):
        if events:
            break
        await asyncio.sleep(0)
    approval_id = events[0]["payload"]["approval_id"]
    request = gate.get_pending(approval_id)
    assert request is not None
    approver = auth_context(world, "faculty")
    edit = {"grade_id": grade_id, "final_scores": {"thesis": 3, "evidence": 3},
            "holistic_md": "Fine."}
    args = await gateway.authorize_approver(request, approver, edit)
    gate.resolve(ApprovalDecision(approval_id, "edit", edit), approver=approver,
                 tool_arguments=args)
    assert (await commit).success

    rows = await pool.fetch(
        "SELECT a.id, a.target_id, a.turn_id, a.session_id, a.subject_person, a.course_node,"
        " a.model, a.prompt_sha256, a.sources, d.decision, d.diff, d.decided_by"
        " FROM ai_actions a LEFT JOIN human_decisions d ON d.ai_action_id = a.id"
        " WHERE a.session_id = $1 AND a.action_type = 'grade_draft'"
        " ORDER BY a.created_at, a.id", uuid.UUID(seed.session))
    by_grade = {str(r["target_id"]): r for r in rows}
    assert len(rows) == 2
    committed = by_grade[grade_id]
    edited = next(r for r in rows if str(r["target_id"]) != grade_id)
    assert committed["decision"] == "accepted"
    assert edited["decision"] == "edited"
    assert json.loads(edited["diff"])["criteria"] == {
        "thesis": {"before": 2, "after": 3, "delta": 1}}
    assert str(edited["decided_by"]) == seed.faculty
    assert str(committed["turn_id"]) == seed.turn
    assert str(committed["subject_person"]) == seed.student
    assert str(committed["course_node"]) == seed.course
    assert (committed["model"], committed["prompt_sha256"]) == ("claude-test", "cd" * 32)
    assert {"type": "submission", "id": seed.submission, "version": None} in json.loads(
        committed["sources"])


async def test_rows_are_idempotent_and_unknown_references_become_null(pool, seed):
    store = PgProvenanceStore(pool)
    recorder = ProvenanceRecorder(store)
    row = AiActionRow(id=str(uuid.uuid4()), agent="tutor", action_type="attestation",
                      output={"level": "mastery"}, session_id=seed.session,
                      turn_id="not-a-persisted-turn", subject_person=str(uuid.uuid4()),
                      course_node=seed.course)
    assert await recorder.record(row) is True
    assert await recorder.record(row) is False

    stored = await pool.fetchrow("SELECT turn_id, subject_person, course_node FROM ai_actions"
                                 " WHERE id = $1", uuid.UUID(row.id))
    assert stored["turn_id"] is None and stored["subject_person"] is None
    assert str(stored["course_node"]) == seed.course


async def test_badge_recommendation_resolves_the_pending_row(pool, seed):
    store = PgProvenanceStore(pool)
    assert await store.pending_credential_id(seed.student, seed.micro) == seed.pending
    assert await store.pending_credential_id(seed.faculty, seed.micro) is None


async def test_decision_endpoint_writes_a_row(pool, seed, world):
    """POST /api/ai-actions/{id}/decisions by the subject learner, against the real tables."""
    store = PgProvenanceStore(pool)
    row = AiActionRow(id=str(uuid.uuid4()), agent="tutor", action_type="nudge",
                      output={"text": "Review recursion"}, subject_person=seed.student,
                      course_node=seed.course)
    await store.record_action(row)

    app = create_app(auth_service=world.service, scope_directory=world.directory,
                     provenance=store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/auth/login", json={
            "username": world.people["student"].email, "password": DEMO_PASSWORD})
        assert login.status_code == 200, login.text
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        resp = await client.post(f"/api/ai-actions/{row.id}/decisions",
                                 json={"decision": "dismissed", "reason": "Not helpful"})
    assert resp.status_code == 201, resp.text

    stored = await pool.fetchrow("SELECT decision, reason, decided_by FROM human_decisions"
                                 " WHERE ai_action_id = $1", uuid.UUID(row.id))
    assert (stored["decision"], stored["reason"], str(stored["decided_by"])) == (
        "dismissed", "Not helpful", seed.student)
