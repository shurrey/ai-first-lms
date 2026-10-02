"""PgTurnRepository against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own rows and
deletes them afterwards.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from engine.auth.repository import create_pool
from engine.guardrails.approval import ApprovalDecision, ApprovalGate
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.tests.auth_fakes import CS101, auth_context, build_auth_world
from engine.tests.object_fakes import InMemoryObjectDirectory
from engine.turn_repository import PgTurnRepository, ToolCallRow

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


@pytest.fixture
async def turn_id(pool) -> AsyncIterator[str]:
    tag = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        person = await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            ["student"], f"Student {tag}", f"student-{tag}@example.test",
        )
        session = await conn.fetchval(
            "INSERT INTO sessions (person_id, persona) VALUES ($1, 'student') RETURNING id",
            person,
        )
        turn = await conn.fetchval(
            "INSERT INTO turns (session_id, user_message) VALUES ($1, 'hi') RETURNING id",
            session,
        )
    try:
        yield str(turn)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = $1", session)
            await conn.execute("DELETE FROM persons WHERE id = $1", person)


def _row(turn_id: str) -> ToolCallRow:
    return ToolCallRow(turn_id=turn_id, agent="tutor", tool="graph.mastery_map",
                       args={"person_id": "p1"}, outcome="denied_scope", latency_ms=3)


async def test_records_a_row_for_a_persisted_turn(pool, turn_id):
    assert await PgTurnRepository(pool).record_tool_call(_row(turn_id)) is True

    row = await pool.fetchrow("SELECT * FROM tool_calls WHERE turn_id = $1", uuid.UUID(turn_id))
    assert (row["agent"], row["tool"], row["outcome"], row["latency_ms"]) == (
        "tutor", "graph.mastery_map", "denied_scope", 3,
    )
    assert json.loads(row["args"]) == {"person_id": "p1"}


async def test_skips_a_turn_without_a_row(pool):
    repo = PgTurnRepository(pool)

    assert await repo.record_tool_call(_row(str(uuid.uuid4()))) is False
    assert await repo.record_tool_call(_row("brief-not-a-uuid")) is False


async def test_gated_and_approved_calls_keep_their_approval_record(pool, turn_id):
    world = build_auth_world()
    gate = ApprovalGate()
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    student_id = world.people["student"].id

    async def mcp(tool: str, args: dict) -> str:
        if tool == "assessments.get_submission":
            return json.dumps({"id": args["submission_id"], "person_id": student_id})
        return '{"committed": true}'

    gateway = ToolGateway(mcp, directory=world.directory,
                          objects=InMemoryObjectDirectory({"s1": CS101.course_id}),
                          turns=PgTurnRepository(pool), approvals=gate, approval_timeout=5)
    gateway.drafts.remember("grade", "g1", world.people["faculty"].id, {"submission_id": "s1"})
    ctx = GatewayContext(auth=auth_context(world, "faculty"), turn_id=turn_id, step_id="s1",
                         course_id=CS101.course_id, emit=emit)
    call = asyncio.create_task(
        gateway.invoke(ctx, "grading_assistant", "assessments.commit_grade", {"grade_id": "g1"}))
    while not events:
        assert not call.done(), call.result()
        await asyncio.sleep(0.01)
    approval_id = events[0]["payload"]["approval_id"]
    gate.resolve(ApprovalDecision(approval_id, "approve"), approver=auth_context(world, "faculty"))
    await call

    rows = await pool.fetch("SELECT outcome, args FROM tool_calls WHERE turn_id = $1 ORDER BY id",
                            uuid.UUID(turn_id))
    assert [r["outcome"] for r in rows] == ["gated", "ok"]
    assert json.loads(rows[0]["args"])["approval_id"] == approval_id
    assert json.loads(rows[1]["args"])["approved_by"] == world.people["faculty"].id
