"""PgObjectDirectory against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test seeds its own rows and
deletes them afterwards.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import pytest

from engine.auth.repository import create_pool
from engine.guardrails.object_directory import PgObjectDirectory

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")


@dataclass
class Seeded:
    course_id: str
    other_course_id: str
    legacy_submission: str  # course only on the assignment's metadata, as the seed writes it
    direct_submission: str  # submissions.course_node set
    bank_id: str


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    assert DSN is not None
    p = await create_pool(DSN)
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def seeded(pool) -> AsyncIterator[Seeded]:
    tag = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        student = await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            ["student"], f"Student {tag}", f"student-{tag}@example.test",
        )
        course = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', $1) RETURNING id", f"Obj IT {tag}")
        other = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', $1) RETURNING id", f"Obj OT {tag}")
        assignment = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('assessment_item', $1, $2::jsonb) "
            "RETURNING id",
            f"Essay {tag}", json.dumps({"course_id": str(course)}),
        )
        legacy = await conn.fetchval(
            "INSERT INTO submissions (person_id, assignment_node) VALUES ($1, $2) RETURNING id",
            student, assignment,
        )
        direct = await conn.fetchval(
            "INSERT INTO submissions (person_id, assignment_node, course_node) "
            "VALUES ($1, $2, $3) RETURNING id",
            student, assignment, other,
        )
        bank = await conn.fetchval(
            "INSERT INTO question_banks (course_node, title) VALUES ($1, $2) RETURNING id",
            course, f"Bank {tag}",
        )
    try:
        yield Seeded(str(course), str(other), str(legacy), str(direct), str(bank))
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM question_banks WHERE id = $1", bank)
            await conn.execute("DELETE FROM submissions WHERE id = ANY($1::uuid[])",
                               [legacy, direct])
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                               [assignment, course, other])
            await conn.execute("DELETE FROM persons WHERE id = $1", student)


async def test_submission_course_falls_back_to_the_assignments_course(pool, seeded):
    objects = PgObjectDirectory(pool)

    assert await objects.submission_course(seeded.legacy_submission) == seeded.course_id
    assert await objects.submission_course(seeded.direct_submission) == seeded.other_course_id


async def test_unknown_or_malformed_ids_resolve_to_none(pool, seeded):
    objects = PgObjectDirectory(pool)

    assert await objects.submission_course(str(uuid.uuid4())) is None
    assert await objects.submission_course("not-a-uuid") is None
    assert await objects.question_bank_course("not-a-uuid") is None


async def test_question_bank_course(pool, seeded):
    assert await PgObjectDirectory(pool).question_bank_course(seeded.bank_id) == seeded.course_id


async def test_app_gateway_uses_the_database_object_directory(monkeypatch):
    from engine.app import create_app

    assert DSN is not None
    monkeypatch.setenv("DATABASE_URL", DSN)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.object_directory, PgObjectDirectory)
        assert app.state.tool_gateway._objects is app.state.object_directory
    assert app.state.object_directory is None
