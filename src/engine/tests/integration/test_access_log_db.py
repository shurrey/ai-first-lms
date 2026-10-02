"""PgAccessLog against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own people and deletes
them, and their log rows, afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace

import asyncpg
import pytest

from engine.auth.access_log import AccessEntry, PgAccessLog
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
