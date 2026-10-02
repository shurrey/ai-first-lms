"""Tests for the canonical 4-course seed (data_mcp.seed.all_courses)."""
from __future__ import annotations

import asyncio
import os
import random
import subprocess
import sys
import uuid

import asyncpg
import pytest
from argon2 import PasswordHasher

from data_mcp.seed.all_courses import MissingDemoPasswordError, seed
from data_mcp.seed.cs101 import seed as seed_legacy_cs101
from data_mcp.seed.demo_accounts import fetch_demo_accounts, format_demo_accounts

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")
TEST_PASSWORD = "test-only-demo-password"


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


class _NoDbConnection:
    def __getattr__(self, name: str):  # noqa: ANN204
        raise AssertionError(f"seed touched the database ({name}) before checking the password")


@pytest.mark.parametrize("value", [None, ""])
def test_seed_fails_fast_without_demo_password(monkeypatch, value) -> None:  # noqa: ANN001
    if value is None:
        monkeypatch.delenv("SEED_DEMO_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("SEED_DEMO_PASSWORD", value)
    with pytest.raises(MissingDemoPasswordError, match="SEED_DEMO_PASSWORD"):
        _run(seed(_NoDbConnection(), random.Random(42)))


def test_seed_cli_exits_nonzero_without_demo_password() -> None:
    env = {k: v for k, v in os.environ.items() if k != "SEED_DEMO_PASSWORD"}
    # Unreachable DB: proves the check runs before connecting.
    env["LMS_DATABASE_URL"] = "postgresql://nobody:nothing@127.0.0.1:1/none"
    proc = subprocess.run(
        [sys.executable, "-m", "data_mcp.seed.all_courses", "--seed", "42"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "SEED_DEMO_PASSWORD is not set" in proc.stderr


def test_format_demo_accounts_aligns_columns() -> None:
    table = format_demo_accounts([
        {"name": "A", "username": "a@x.edu", "roles": "student", "courses": "CS 101"},
    ])
    assert table.splitlines() == [
        "Name  Username  Roles    Courses",
        "----  --------  -------  -------",
        "A     a@x.edu   student  CS 101",
    ]


# ── DB-backed: these TRUNCATE everything, then restore the legacy cs101 seed ──

db = pytest.mark.skipif(
    DB_URL.rstrip("/").endswith("/lms_db"),
    reason="destructive seed tests never run against lms_db; set LMS_DATABASE_URL to lms_test",
)


@pytest.fixture(scope="module")
def seeded() -> dict:
    async def _seed() -> dict:
        conn = await asyncpg.connect(DB_URL)
        try:
            return await seed(conn, random.Random(42), TEST_PASSWORD)
        finally:
            await conn.close()

    async def _restore_legacy() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            await seed_legacy_cs101(conn, random.Random(42))
        finally:
            await conn.close()

    summary = _run(_seed())
    yield summary
    _run(_restore_legacy())


async def _fetch(query: str, *args):  # noqa: ANN002, ANN202
    conn = await asyncpg.connect(DB_URL)
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


@db
def test_every_person_has_credentials_that_verify(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT p.email, c.username, c.password_hash, c.must_change
           FROM persons p LEFT JOIN credentials c ON c.person_id = p.id"""
    ))
    assert len(rows) == 59 == seeded["credentials"]
    hasher = PasswordHasher()
    for r in rows:
        assert r["username"] == r["email"]
        assert r["must_change"] is False
        assert r["password_hash"].startswith("$argon2id$")
        assert hasher.verify(r["password_hash"], TEST_PASSWORD)
    assert len({r["password_hash"] for r in rows}) == len(rows)


@db
def test_username_lookup_is_case_insensitive(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch("SELECT 1 FROM credentials WHERE username = 'A.OKAFOR@University.edu'"))
    assert len(rows) == 1


@db
def test_advisor_assigned_all_students_without_enrollments(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT count(*) AS n, count(DISTINCT a.student_id) AS students
           FROM advisor_assignments a
           JOIN persons adv ON adv.id = a.advisor_id AND adv.email = 'a.okafor@university.edu'
           JOIN persons s ON s.id = a.student_id AND s.roles @> '{student}'"""
    ))
    assert (rows[0]["n"], rows[0]["students"]) == (50, 50)
    total = _run(_fetch("SELECT count(*) AS n FROM advisor_assignments"))
    assert total[0]["n"] == 50


@db
def test_no_advisor_or_admin_enrollments(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT e.role, p.email FROM enrollments e JOIN persons p ON p.id = e.person_id
           WHERE e.role IN ('advisor', 'admin')
              OR p.email IN ('a.okafor@university.edu', 'r.hayes@university.edu')"""
    ))
    assert rows == []


@db
def test_torres_is_faculty_and_program_lead(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch("SELECT roles FROM persons WHERE email = 'm.torres@university.edu'"))
    assert rows[0]["roles"] == ["faculty", "program_lead"]
    leads = _run(_fetch("SELECT count(*) AS n FROM persons WHERE roles @> '{program_lead}'"))
    assert leads[0]["n"] == 1


@db
def test_course_nodes_carry_slugs(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch("SELECT id, metadata->>'slug' AS slug FROM nodes WHERE kind = 'course'"))
    assert {r["slug"]: str(r["id"]) for r in rows} == seeded["course_ids"]
    assert set(seeded["course_ids"]) == {"cs101", "math201", "eng102", "bio150"}


@db
def test_demo_accounts_match_spec(seeded) -> None:  # noqa: ANN001
    async def _accounts() -> list[dict]:
        conn = await asyncpg.connect(DB_URL)
        try:
            return await fetch_demo_accounts(conn)
        finally:
            await conn.close()

    accounts = {a["name"]: a for a in _run(_accounts())}
    assert accounts["Emma Smith"]["courses"] == "BIO 150, CS 101, MATH 201"
    assert "ENG 102" in accounts["Noah Brown"]["courses"]
    assert accounts["Dr. Maria Torres"]["roles"] == "faculty, program_lead"
    assert accounts["Dr. Sarah Chen"]["courses"] == "MATH 201"
    assert accounts["Dr. Emily Watson"]["courses"] == "ENG 102"
    assert accounts["Dr. Michael Patel"]["courses"] == "BIO 150"
    assert accounts["Ms. Adaeze Okafor"]["courses"] == "50 advisees"
    assert accounts["Dr. Richard Hayes"]["courses"] == "institution"
    assert TEST_PASSWORD not in format_demo_accounts(list(accounts.values()))


@db
def test_skill_documents_survive_reseed(seeded) -> None:  # noqa: ANN001
    async def _reseed_with_skill() -> tuple[uuid.UUID, list]:
        conn = await asyncpg.connect(DB_URL)
        try:
            concept = await conn.fetchrow(
                "SELECT id FROM nodes WHERE kind = 'concept' ORDER BY id LIMIT 1"
            )
            skill_id = await conn.fetchval(
                """INSERT INTO content_items (node_id, kind, title, body_md)
                   VALUES ($1, 'skill', 'Skill: test', '# generated') RETURNING id""",
                concept["id"],
            )
            summary = await seed(conn, random.Random(42), TEST_PASSWORD)
            rows = await conn.fetch(
                "SELECT node_id, body_md FROM content_items WHERE id = $1", skill_id,
            )
            assert summary["skills_preserved"] >= 1
            assert summary["skills_dropped"] == 0
            return concept["id"], rows
        finally:
            await conn.close()

    concept_id, rows = _run(_reseed_with_skill())
    assert [(r["node_id"], r["body_md"]) for r in rows] == [(concept_id, "# generated")]


@db
def test_reseed_is_deterministic(seeded) -> None:  # noqa: ANN001
    async def _reseed() -> dict:
        conn = await asyncpg.connect(DB_URL)
        try:
            return await seed(conn, random.Random(42), TEST_PASSWORD)
        finally:
            await conn.close()

    again = _run(_reseed())
    assert again["course_ids"] == seeded["course_ids"]
    assert again["total_edges"] == seeded["total_edges"]
    assert again["total_evidence"] == seeded["total_evidence"]
