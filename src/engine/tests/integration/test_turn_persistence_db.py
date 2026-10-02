"""Turn persistence and SSE replay across an app restart, against a real Postgres.

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own person and
deletes its sessions, turns and events afterwards.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.auth.repository import create_pool
from engine.models.session import Session
from engine.models.turn import Turn
from engine.tests.auth_fakes import DEMO_PASSWORD, AuthWorld, build_auth_world
from engine.turn_repository import PgTurnRepository, ToolCallRow, turn_db_id

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")

EVENTS = [
    {"event": "reasoning", "payload": {"step": "interpret", "text": "Thinking"}},
    {"event": "plan", "payload": {"strategy": "react", "steps": []}},
    {"event": "final", "payload": {"answer_markdown": "Done", "artifacts": [],
                                   "cost_usd": 0.01, "tokens": 50, "wall_time_ms": 9}},
]


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    assert DSN is not None
    p = await create_pool(DSN)
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def world(pool) -> AsyncIterator[AuthWorld]:
    """An auth world whose student also exists in `persons`, so sessions can reference it."""
    w = build_auth_world()
    student = w.people["student"]
    person_id = uuid.UUID(student.id)
    await pool.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        person_id, ["student"], student.display_name,
        f"persist-{uuid.uuid4().hex[:8]}@example.test",
    )
    try:
        yield w
    finally:
        async with pool.acquire() as conn:
            sessions = await conn.fetch("SELECT id FROM sessions WHERE person_id = $1",
                                        person_id)
            ids = [r["id"] for r in sessions]
            await conn.execute("DELETE FROM events_log WHERE session_id = ANY($1::uuid[])", ids)
            await conn.execute("DELETE FROM sessions WHERE person_id = $1", person_id)
            await conn.execute("DELETE FROM persons WHERE id = $1", person_id)


def _app(world: AuthWorld, pool: asyncpg.Pool):
    return create_app(auth_service=world.service, scope_directory=world.directory,
                      persistence=PgTurnRepository(pool))


@asynccontextmanager
async def _signed_in(app, world: AuthWorld) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/login", json={
            "username": world.people["student"].email, "password": DEMO_PASSWORD})
        assert resp.status_code == 200, resp.text
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        yield client


def _envelopes(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines()
            if line.startswith("data: ")]


async def _run_turn(app, world: AuthWorld, *, turn_id: str | None = None,
                    finish: bool = True) -> tuple[str, str]:
    session = Session(persona="student", person_id=world.people["student"].id,
                      course_id="all", requester_name="Emma")
    await app.state.session_store.create(session)
    turn = Turn(session_id=session.id, message="hello")
    if turn_id is not None:
        turn.id = turn_id
    await app.state.turn_store.create(turn)
    await app.state.turn_store.add_events(turn.id, EVENTS)
    if finish:
        await app.state.turn_store.record_usage(turn.id, 0.01, 50)
        await app.state.turn_store.update_status(turn.id, "completed")
    return session.id, turn.id


async def test_turn_and_events_are_written(pool, world):
    _, turn_id = await _run_turn(_app(world, pool), world)

    row = await pool.fetchrow("SELECT * FROM turns WHERE id = $1", uuid.UUID(turn_id))
    assert (row["user_message"], row["status"], row["tokens"]) == ("hello", "done", 50)
    assert row["completed_at"] is not None
    logged = await pool.fetch(
        "SELECT sequence, event_type FROM events_log WHERE turn_id = $1 ORDER BY sequence",
        uuid.UUID(turn_id))
    assert [(r["sequence"], r["event_type"]) for r in logged] == [
        (1, "reasoning"), (2, "plan"), (3, "final")]


async def test_tool_calls_attach_to_the_persisted_turn(pool, world):
    _, turn_id = await _run_turn(_app(world, pool), world)
    row = ToolCallRow(turn_id=turn_id, agent="tutor", tool="content.retrieve", args={},
                      outcome="ok", latency_ms=1)
    assert await PgTurnRepository(pool).record_tool_call(row) is True


async def test_stream_replays_from_events_log_after_restart(pool, world):
    before = _app(world, pool)
    session_id, turn_id = await _run_turn(before, world)
    url = f"/api/stream?session_id={session_id}&turn_id={turn_id}"
    async with _signed_in(before, world) as client:
        original = _envelopes((await client.get(url)).text)

    async with _signed_in(_app(world, pool), world) as client:
        resp = await client.get(url + "&since_sequence=1")

    assert resp.status_code == 200
    assert _envelopes(resp.text) == original[1:]
    assert [e["sequence"] for e in original] == [1, 2, 3]


async def test_brief_turn_id_round_trips(pool, world):
    session_id = str(uuid.uuid4())
    before = _app(world, pool)
    await before.state.session_store.create(Session(
        id=session_id, persona="student", person_id=world.people["student"].id,
        course_id="all"))
    brief = Turn(session_id=session_id, message="__brief__")
    brief.id = f"brief-{session_id}"
    await before.state.turn_store.create(brief)
    await before.state.turn_store.add_events(brief.id, EVENTS)
    await before.state.turn_store.update_status(brief.id, "completed")

    assert await pool.fetchval("SELECT count(*) FROM events_log WHERE turn_id = $1",
                               turn_db_id(brief.id)) == 3
    async with _signed_in(_app(world, pool), world) as client:
        resp = await client.get(f"/api/stream?session_id={session_id}&turn_id={brief.id}")
    assert [e["event"] for e in _envelopes(resp.text)] == ["reasoning", "plan", "final"]


async def test_turn_running_at_restart_replays_then_reports_interruption(pool, world):
    session_id, turn_id = await _run_turn(_app(world, pool), world, finish=False)

    async with _signed_in(_app(world, pool), world) as client:
        resp = await client.get(
            f"/api/stream?session_id={session_id}&turn_id={turn_id}&since_sequence=3")

    assert [(e["sequence"], e["event"]) for e in _envelopes(resp.text)] == [(4, "error")]
    assert await pool.fetchval("SELECT status FROM turns WHERE id = $1",
                               uuid.UUID(turn_id)) == "error"
