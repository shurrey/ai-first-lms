"""Tests for the Alembic migration producing contracts/db-schema.sql."""
from __future__ import annotations

import asyncio
import os
import subprocess

import asyncpg
import pytest

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "LMS_DATABASE_URL": DB_URL},
        cwd=ROOT_DIR,
    )


def _clean_db() -> None:
    """Drop all objects so we test from a clean slate."""

    async def _drop() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        finally:
            await conn.close()

    asyncio.run(_drop())


@pytest.fixture(autouse=True, scope="module")
def migrate_fresh() -> None:
    """Clean DB and run alembic upgrade head once for the whole module."""
    _clean_db()
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"


def test_alembic_current_shows_head() -> None:
    result = _run_alembic("current")
    assert result.returncode == 0, f"alembic current failed:\n{result.stderr}"
    assert "001" in result.stdout, f"Expected 001 in output:\n{result.stdout}"


def test_schema_tables_exist() -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = {r["tablename"] for r in rows}
            expected = {
                "nodes", "edges", "persons", "enrollments", "evidence",
                "attestations", "content_items", "question_banks", "questions",
                "rubrics", "submissions", "grades", "messages", "message_templates",
                "standards_frameworks", "standards", "intervention_playbook",
                "sessions", "turns", "events_log", "alembic_version",
            }
            missing = expected - tables
            assert not missing, f"Missing tables: {missing}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_schema_views_exist() -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT viewname FROM pg_views WHERE schemaname = 'public' ORDER BY viewname"
            )
            views = {r["viewname"] for r in rows}
            expected = {"courses", "modules", "assignments", "gradebook"}
            missing = expected - views
            assert not missing, f"Missing views: {missing}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_schema_enums_exist() -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT typname FROM pg_type WHERE typtype = 'e' ORDER BY typname"
            )
            enums = {r["typname"] for r in rows}
            expected = {"node_kind", "edge_kind", "evidence_kind", "attestation_level"}
            missing = expected - enums
            assert not missing, f"Missing enums: {missing}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_idempotent_upgrade() -> None:
    """Running upgrade again should be a no-op (already at head)."""
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"Second upgrade failed:\n{result.stderr}"
