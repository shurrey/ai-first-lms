"""Tests for LMS projection views — verify graph data projects correctly."""
from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def seed_data() -> dict:
    """Insert test graph data and return IDs for assertions."""
    ids: dict = {}

    async def _seed() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            # Clean up any previous test data
            await conn.execute("DELETE FROM grades")
            await conn.execute("DELETE FROM submissions")
            await conn.execute("DELETE FROM enrollments")
            await conn.execute("DELETE FROM evidence")
            await conn.execute("DELETE FROM edges")
            await conn.execute("DELETE FROM content_items")
            await conn.execute("DELETE FROM nodes WHERE kind IN ('course', 'module', 'assessment_item')")
            await conn.execute("DELETE FROM persons")

            # Create a course node
            course_id = uuid.uuid4()
            ids["course_id"] = course_id
            await conn.execute(
                """INSERT INTO nodes (id, kind, title, description)
                   VALUES ($1, 'course', 'CS 101', 'Intro to CS')""",
                course_id,
            )

            # Create module nodes with part_of edges to course
            mod1_id = uuid.uuid4()
            mod2_id = uuid.uuid4()
            ids["mod1_id"] = mod1_id
            ids["mod2_id"] = mod2_id
            await conn.execute(
                """INSERT INTO nodes (id, kind, title) VALUES ($1, 'module', 'Variables')""",
                mod1_id,
            )
            await conn.execute(
                """INSERT INTO nodes (id, kind, title) VALUES ($1, 'module', 'Control Flow')""",
                mod2_id,
            )
            # part_of edges: module -> course
            await conn.execute(
                """INSERT INTO edges (from_node, to_node, kind)
                   VALUES ($1, $2, 'part_of')""",
                mod1_id, course_id,
            )
            await conn.execute(
                """INSERT INTO edges (from_node, to_node, kind)
                   VALUES ($1, $2, 'part_of')""",
                mod2_id, course_id,
            )

            # Create an assessment_item with due_at in metadata
            assign_id = uuid.uuid4()
            ids["assign_id"] = assign_id
            await conn.execute(
                """INSERT INTO nodes (id, kind, title, metadata)
                   VALUES ($1, 'assessment_item', 'HW1',
                           $2::jsonb)""",
                assign_id,
                f'{{"due_at": "2026-10-15T23:59:00Z", "course_id": "{course_id}"}}',
            )

            # Create a person and enrollment
            person_id = uuid.uuid4()
            ids["person_id"] = person_id
            await conn.execute(
                """INSERT INTO persons (id, roles, display_name, email)
                   VALUES ($1, $2, 'Alice Student', 'alice@example.com')""",
                person_id, ["student"],
            )
            await conn.execute(
                """INSERT INTO enrollments (person_id, course_node, role)
                   VALUES ($1, $2, 'student')""",
                person_id, course_id,
            )

            # Create a submission and grade for gradebook view
            sub_id = uuid.uuid4()
            ids["sub_id"] = sub_id
            await conn.execute(
                """INSERT INTO submissions (id, person_id, assignment_node, body_md)
                   VALUES ($1, $2, $3, 'My answer')""",
                sub_id, person_id, assign_id,
            )
            grade_id = uuid.uuid4()
            ids["grade_id"] = grade_id
            await conn.execute(
                """INSERT INTO grades (id, submission_id, scores, feedback, holistic_md, is_draft)
                   VALUES ($1, $2, '{"q1": 10}'::jsonb, '{"q1": "Good"}'::jsonb, 'Well done', false)""",
                grade_id, sub_id,
            )
        finally:
            await conn.close()

    _run(_seed())
    return ids


def test_courses_view(seed_data: dict) -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch("SELECT * FROM courses WHERE course_id = $1", seed_data["course_id"])
            assert len(rows) == 1
            assert rows[0]["title"] == "CS 101"
        finally:
            await conn.close()

    _run(_check())


def test_modules_view(seed_data: dict) -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT * FROM modules WHERE course_id = $1 ORDER BY title",
                seed_data["course_id"],
            )
            assert len(rows) == 2
            assert rows[0]["title"] == "Control Flow"
            assert rows[1]["title"] == "Variables"
        finally:
            await conn.close()

    _run(_check())


def test_assignments_view(seed_data: dict) -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT * FROM assignments WHERE assignment_id = $1",
                seed_data["assign_id"],
            )
            assert len(rows) == 1
            assert rows[0]["title"] == "HW1"
            assert rows[0]["course_id"] == seed_data["course_id"]
            assert rows[0]["due_at"] is not None
        finally:
            await conn.close()

    _run(_check())


def test_gradebook_view(seed_data: dict) -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT * FROM gradebook WHERE grade_id = $1",
                seed_data["grade_id"],
            )
            assert len(rows) == 1
            assert rows[0]["person_id"] == seed_data["person_id"]
            assert rows[0]["assignment_id"] == seed_data["assign_id"]
            assert rows[0]["is_draft"] is False
        finally:
            await conn.close()

    _run(_check())
