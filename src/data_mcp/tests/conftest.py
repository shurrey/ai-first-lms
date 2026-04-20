from __future__ import annotations

import asyncio
import os
import random

import asyncpg
import pytest

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")


@pytest.fixture(scope="module")
def event_loop_policy():
    """Use the default event loop policy for module-scoped async fixtures."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session", autouse=True)
def ensure_seeded():
    """Ensure the database is seeded before any tests run."""

    async def _check_and_seed() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM persons WHERE roles @> '{student}'")
            if row["c"] < 50:
                from data_mcp.seed.cs101 import seed
                rng = random.Random(42)
                await seed(conn, rng)
        finally:
            await conn.close()

    asyncio.run(_check_and_seed())
    yield
    # Re-seed after all tests to leave DB clean for next run
    asyncio.run(_check_and_seed())
