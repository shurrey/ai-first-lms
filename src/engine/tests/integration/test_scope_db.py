"""PgScopeDirectory against a real Postgres (Alembic head).

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

from engine.auth.directory import PgScopeDirectory, SessionOwner
from engine.auth.repository import create_pool

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")


@dataclass
class Seeded:
    lead_id: str
    student_id: str
    course_id: str
    slug: str
    titled_course_id: str
    session_id: str
    pending_id: str


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
    slug = f"zz{tag}"
    async with pool.acquire() as conn:
        lead = await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            ["faculty", "program_lead"], f"Lead {tag}", f"lead-{tag}@example.test",
        )
        student = await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            ["student"], f"Student {tag}", f"student-{tag}@example.test",
        )
        course = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('course', $1, $2::jsonb) "
            "RETURNING id",
            f"Scope IT {tag}", json.dumps({"slug": slug}),
        )
        titled = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', $1) RETURNING id",
            f"QQ{tag[:3]} 7{tag[3:5]} — Untitled slug",
        )
        program = await conn.fetchval(
            "INSERT INTO nodes (kind, title, metadata) VALUES ('program', $1, $2::jsonb) "
            "RETURNING id",
            f"Program {tag}", json.dumps({"program_lead_ids": [str(lead)]}),
        )
        microcredential = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('microcredential', $1) RETURNING id",
            f"Badge {tag}",
        )
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
            course, program,
        )
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'student')",
            student, course,
        )
        session = await conn.fetchval(
            "INSERT INTO sessions (person_id, persona, course_node) "
            "VALUES ($1, 'student', $2) RETURNING id",
            student, course,
        )
        pending = await conn.fetchval(
            "INSERT INTO pending_credentials (person_id, microcredential_id, course_id) "
            "VALUES ($1, $2, $3) RETURNING id",
            student, microcredential, course,
        )
    try:
        yield Seeded(str(lead), str(student), str(course), slug, str(titled), str(session),
                     str(pending))
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = $1", session)
            await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])", [lead, student])
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                               [course, titled, program, microcredential])


async def test_resolves_course_by_uuid_metadata_slug_and_title(pool, seeded):
    directory = PgScopeDirectory(pool)
    assert (await directory.resolve_course(seeded.course_id)).slug == seeded.slug
    assert (await directory.resolve_course(seeded.slug.upper())).id == seeded.course_id
    titled = await directory.resolve_course(seeded.titled_course_id)
    assert titled is not None
    assert (await directory.resolve_course(titled.slug)).id == seeded.titled_course_id
    assert await directory.resolve_course("no-such-course-slug") is None


async def test_enrollment_and_advisee_course_lookups(pool, seeded):
    directory = PgScopeDirectory(pool)
    assert await directory.student_course_ids(seeded.student_id) == {seeded.course_id}
    assert await directory.course_ids_with_students([seeded.student_id, "not-a-uuid"]) == {
        seeded.course_id
    }
    assert await directory.student_course_ids("not-a-uuid") == frozenset()


async def test_session_and_pending_credential_lookups(pool, seeded):
    directory = PgScopeDirectory(pool)
    assert await directory.session_owner(seeded.session_id) == SessionOwner(
        seeded.student_id, seeded.course_id
    )
    assert await directory.session_owner(str(uuid.uuid4())) is None
    assert await directory.session_owner("brief-x") is None
    assert await directory.pending_credential_course(seeded.pending_id) == seeded.course_id


async def test_program_courses_for_a_named_lead_only(pool, seeded):
    directory = PgScopeDirectory(pool)
    assert await directory.program_course_ids(seeded.lead_id) == {seeded.course_id}
    assert await directory.program_course_ids(seeded.student_id) is None


async def test_count_persons_with_role(pool, seeded):
    directory = PgScopeDirectory(pool)
    assert await directory.count_persons_with_role("program_lead") >= 1
