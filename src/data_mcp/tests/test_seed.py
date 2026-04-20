"""Tests for the deterministic seed script."""
from __future__ import annotations

import asyncio
import os

import asyncpg

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


def test_seed_produces_expected_counts() -> None:
    """Verify the seed creates the expected number of entities."""

    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            # Students
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM persons WHERE roles @> '{student}'")
            assert row["c"] == 50, f"Expected 50 students, got {row['c']}"

            # Faculty
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM persons WHERE roles @> '{faculty}'")
            assert row["c"] == 2

            # Advisor
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM persons WHERE roles @> '{advisor}'")
            assert row["c"] == 1

            # Course
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM courses")
            assert row["c"] == 1

            # Modules
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM modules")
            assert row["c"] == 12

            # Concepts
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM nodes WHERE kind = 'concept'")
            assert row["c"] == 192

            # Skills
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM nodes WHERE kind = 'skill'")
            assert row["c"] == 72

            # Assignments (assessment items with due_at)
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM assignments")
            assert row["c"] == 7

            # Evidence > 0
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM evidence")
            assert row["c"] > 1000

            # Submissions > 0
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM submissions")
            assert row["c"] > 100

        finally:
            await conn.close()

    _run(_check())


def test_seed_is_deterministic() -> None:
    """Running seed with the same seed value produces the same person IDs."""
    import random
    from data_mcp.seed.cs101 import seed

    async def _check() -> None:
        rng1 = random.Random(42)
        conn1 = await asyncpg.connect(DB_URL)
        try:
            await seed(conn1, rng1)
            ids1 = await conn1.fetch("SELECT id FROM persons ORDER BY id")
        finally:
            await conn1.close()

        rng2 = random.Random(42)
        conn2 = await asyncpg.connect(DB_URL)
        try:
            await seed(conn2, rng2)
            ids2 = await conn2.fetch("SELECT id FROM persons ORDER BY id")
        finally:
            await conn2.close()

        assert [r["id"] for r in ids1] == [r["id"] for r in ids2], "Seed is not deterministic!"

    _run(_check())


def test_seed_idempotent() -> None:
    """Running seed twice doesn't error (truncates and re-seeds)."""
    import random
    from data_mcp.seed.cs101 import seed

    async def _check() -> None:
        rng = random.Random(42)
        conn = await asyncpg.connect(DB_URL)
        try:
            await seed(conn, rng)
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM persons")
            assert row["c"] == 53  # 50 students + 2 faculty + 1 advisor
        finally:
            await conn.close()

    _run(_check())
