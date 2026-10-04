"""PgAccessLog against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own people and deletes
them, and their log rows, afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.access_log import AccessEntry, PgAccessLog
from engine.auth.deps import current_user
from engine.auth.models import AuthContext
from engine.auth.repository import create_pool
from engine.auth.scope import SensitiveRead, can_view_student
from engine.tests.auth_fakes import auth_context, build_auth_world

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
async def people(pool) -> AsyncIterator[tuple[str, str]]:
    """(actor_id, subject_id)."""
    tag = uuid.uuid4().hex[:8]
    ids = []
    async with pool.acquire() as conn:
        for role in ("admin", "student"):
            ids.append(str(await conn.fetchval(
                "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) "
                "RETURNING id",
                [role], f"AccessLog {role} {tag}", f"accesslog-{role}-{tag}@example.test",
            )))
    try:
        yield ids[0], ids[1]
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM data_access_log WHERE actor_id = ANY($1::uuid[]) "
                               "OR subject_id = ANY($1::uuid[])", ids)
            await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])", ids)


async def test_record_and_list_by_subject(pool, people):
    actor, subject = people
    log = PgAccessLog(pool)
    session_id = str(uuid.uuid4())

    await log.record(AccessEntry(actor, subject, "profile", None, "first"))
    await log.record(AccessEntry(actor, subject, "transcript", session_id, "second"))
    await log.record(AccessEntry(actor, subject, "submission", "not-a-uuid", "third"))

    rows = await log.list_by_subject(subject)
    assert [(r.resource, r.resource_id, r.purpose) for r in rows] == [
        ("submission", None, "third"),
        ("transcript", session_id, "second"),
        ("profile", None, "first"),
    ]
    assert all(r.actor_id == actor and r.subject_id == subject for r in rows)
    assert [r.purpose for r in await log.list_by_subject(subject, limit=1)] == ["third"]
    assert await log.list_by_subject(actor) == []
    assert await log.list_by_subject("not-a-uuid") == []


async def test_can_view_student_writes_a_row(pool, people):
    actor, subject = people
    world = build_auth_world()
    ctx: AuthContext = replace(auth_context(world, "admin"), person_id=actor)

    allowed = await can_view_student(ctx, subject, purpose="admin_review",
                                     directory=world.directory,
                                     read=SensitiveRead(PgAccessLog(pool), "profile"))

    assert allowed
    rows = await PgAccessLog(pool).list_by_subject(subject)
    assert [(r.actor_id, r.resource, r.purpose) for r in rows] == [
        (actor, "profile", "admin_review")]


async def test_record_many_writes_every_row(pool, people):
    actor, subject = people
    log = PgAccessLog(pool)

    await log.record_many([AccessEntry(actor, subject, "ai_actions", None, "measurement_export"),
                           AccessEntry(subject, actor, "ai_actions", None, "measurement_export")])
    await log.record_many([])

    assert [(r.actor_id, r.resource, r.purpose) for r in await log.list_by_subject(subject)] \
        == [(actor, "ai_actions", "measurement_export")]
    assert [r.actor_id for r in await log.list_by_subject(actor)] == [subject]


async def test_admin_endpoint_filters_and_pages_through_rows_with_equal_timestamps(pool, people):
    """Three rows share one created_at, so paging must break ties by id."""
    actor, subject = people
    same = datetime(2026, 9, 1, 12, tzinfo=UTC)
    async with pool.acquire() as conn:
        for purpose, resource, at in (("old", "profile", same - timedelta(days=1)),
                                      ("a", "transcript", same), ("b", "profile", same),
                                      ("c", "transcript", same)):
            await conn.execute(
                "INSERT INTO data_access_log (actor_id, subject_id, resource, purpose,"
                " created_at) VALUES ($1, $2, $3, $4, $5)",
                uuid.UUID(actor), uuid.UUID(subject), resource, purpose, at)
    world = build_auth_world()
    admin = replace(auth_context(world, "admin"), person_id=actor)
    app = create_app(auth_service=world.service, scope_directory=world.directory,
                     access_log=PgAccessLog(pool))
    app.dependency_overrides[current_user] = lambda: admin

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        purposes, before = [], None
        while True:
            params = {"subject_id": subject, "limit": 2, **({"before": before} if before else {})}
            page = (await client.get("/api/access-log", params=params)).json()
            purposes += [e["purpose"] for e in page["entries"]]
            before = page["next_before"]
            if before is None:
                break
        filtered = (await client.get("/api/access-log", params={
            "subject_id": subject, "resource": "transcript",
            "from": same.isoformat(), "to": (same + timedelta(seconds=1)).isoformat()})).json()

    assert purposes == ["c", "b", "a", "old"]
    assert [e["purpose"] for e in filtered["entries"]] == ["c", "a"]
    assert filtered["entries"][0]["actor"]["display_name"].startswith("AccessLog admin")
