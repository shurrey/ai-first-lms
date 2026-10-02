"""Tests for the canonical 4-course seed (data_mcp.seed.all_courses)."""
from __future__ import annotations

import asyncio
import json
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
            assert summary["provenance"] == seeded["provenance"]
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


# ── Provenance history (spec §6.3, §6.6) ──

_PROVENANCE_SNAPSHOT = {
    "ai_actions": """SELECT id, agent, action_type, subject_person, course_node, target_type,
                            sources, model, prompt_sha256, output, created_at
                     FROM ai_actions ORDER BY id""",
    "human_decisions": """SELECT id, ai_action_id, decided_by, decision, diff, reason, decided_at
                          FROM human_decisions ORDER BY id""",
    # evidence ids come from the DB default, so compare the link by its content.
    "outcome_links": """SELECT ai_action_id, delta, observed_at FROM outcome_links
                        ORDER BY ai_action_id, observed_at""",
}


def _provenance_snapshot() -> dict[str, list[dict]]:
    return {k: [dict(r) for r in _run(_fetch(q))] for k, q in _PROVENANCE_SNAPSHOT.items()}


@db
def test_provenance_covers_both_courses_and_all_action_types(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT n.metadata->>'slug' AS slug, a.action_type, count(*) AS n
           FROM ai_actions a JOIN nodes n ON n.id = a.course_node GROUP BY 1, 2"""
    ))
    by_course: dict[str, set[str]] = {}
    for r in rows:
        by_course.setdefault(r["slug"], set()).add(r["action_type"])
    expected = {"grade_draft", "generation", "attestation", "recommendation", "profile_update"}
    assert by_course == {"cs101": expected, "eng102": expected}
    assert seeded["provenance"]["ai_actions"] == sum(r["n"] for r in rows)
    totals = _run(_fetch(
        """SELECT (SELECT count(*) FROM human_decisions) AS d,
                  (SELECT count(*) FROM outcome_links) AS o,
                  (SELECT count(DISTINCT ai_action_id) FROM human_decisions) AS decided,
                  (SELECT count(*) FROM ai_actions) AS a"""
    ))[0]
    assert totals["d"] == seeded["provenance"]["human_decisions"]
    assert totals["o"] == seeded["provenance"]["outcome_links"] > 0
    assert totals["decided"] > totals["a"] / 2


@db
def test_grade_drafts_match_seeded_grades(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT g.is_draft, g.scores, g.graded_by, s.person_id, a.subject_person,
                  a.output->'scores' AS ai_scores, h.decision, h.decided_by, h.diff
           FROM grades g
           JOIN submissions s ON s.id = g.submission_id
           JOIN nodes n ON n.id = s.assignment_node
           LEFT JOIN ai_actions a ON a.target_type = 'grades' AND a.target_id = g.id
           LEFT JOIN human_decisions h ON h.ai_action_id = a.id
           WHERE n.metadata->>'course_id' IN (
               SELECT id::text FROM nodes WHERE metadata->>'slug' IN ('cs101', 'eng102'))"""
    ))
    assert rows and all(r["ai_scores"] is not None for r in rows)
    decisions = {"accepted": 0, "edited": 0, "rejected": 0}
    for r in rows:
        final, ai = json.loads(r["scores"]), json.loads(r["ai_scores"])
        assert r["subject_person"] == r["person_id"]
        if r["is_draft"]:
            assert r["decision"] is None
            assert ai == final
            continue
        decisions[r["decision"]] += 1
        assert r["decided_by"] == r["graded_by"]
        changed = {c["key"]: c for c in json.loads(r["diff"])["criteria"]}
        assert set(changed) == {k for k in final if final[k] != ai[k]}
        for key, c in changed.items():
            assert (c["ai_score"], c["final_score"]) == (ai[key], final[key])
            assert c["delta"] == final[key] - ai[key] != 0
        assert bool(changed) == (r["decision"] != "accepted")
    assert all(n > 0 for n in decisions.values()), decisions


@db
def test_provenance_references_are_consistent(seeded) -> None:  # noqa: ANN001
    orphans = _run(_fetch(
        """SELECT a.id, a.target_type FROM ai_actions a
           WHERE (a.target_type = 'grades'
                  AND NOT EXISTS (SELECT 1 FROM grades WHERE id = a.target_id))
              OR (a.target_type = 'content_items'
                  AND NOT EXISTS (SELECT 1 FROM content_items WHERE id = a.target_id))
              OR (a.target_type = 'attestations'
                  AND NOT EXISTS (SELECT 1 FROM attestations WHERE id = a.target_id))
              OR (a.target_type = 'nodes'
                  AND NOT EXISTS (SELECT 1 FROM nodes WHERE id = a.target_id))
              OR (a.subject_person IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM enrollments e WHERE e.person_id = a.subject_person
                      AND e.course_node = a.course_node AND e.role = 'student'))"""
    ))
    assert orphans == []
    deciders = _run(_fetch(
        """SELECT h.decision, h.decided_by, a.subject_person, e.role
           FROM human_decisions h JOIN ai_actions a ON a.id = h.ai_action_id
           LEFT JOIN enrollments e ON e.person_id = h.decided_by AND e.course_node = a.course_node
           WHERE h.decided_at < a.created_at
              OR (h.decision = 'disputed' AND h.decided_by <> a.subject_person)
              OR (h.decision <> 'disputed' AND e.role IS DISTINCT FROM 'faculty')"""
    ))
    assert deciders == []
    links = _run(_fetch(
        """SELECT o.ai_action_id FROM outcome_links o
           JOIN ai_actions a ON a.id = o.ai_action_id
           JOIN human_decisions h ON h.ai_action_id = a.id
           LEFT JOIN evidence ev ON ev.id = o.evidence_id
           WHERE ev.id IS NULL OR ev.person_id <> a.subject_person
              OR o.observed_at <= h.decided_at OR o.delta->>'criterion' IS NULL"""
    ))
    assert links == []


@db
def test_provenance_reseed_is_deterministic_and_idempotent(seeded) -> None:  # noqa: ANN001
    before = _provenance_snapshot()

    async def _reseed() -> dict:
        conn = await asyncpg.connect(DB_URL)
        try:
            return await seed(conn, random.Random(42), TEST_PASSWORD)
        finally:
            await conn.close()

    again = _run(_reseed())
    assert again["provenance"] == seeded["provenance"]
    assert _provenance_snapshot() == before


# ── Evidence visibility (spec §12.5) ──

_VISIBILITY_BY_SOURCE = """
    SELECT ev.kind::text AS kind, ev.visibility,
           CASE WHEN g.id IS NULL THEN 'ungraded'
                WHEN g.is_draft THEN 'draft' ELSE 'committed' END AS grade,
           count(*) AS n
    FROM evidence ev
    LEFT JOIN submissions s
           ON ev.kind = 'artifact_submission'
          AND s.person_id = ev.person_id AND s.assignment_node = ev.node_id
    LEFT JOIN grades g ON g.submission_id = s.id
    GROUP BY 1, 2, 3"""


@db
def test_only_committed_grade_evidence_is_course_visible(seeded) -> None:  # noqa: ANN001
    rows = {(r["kind"], r["grade"], r["visibility"]): r["n"]
            for r in _run(_fetch(_VISIBILITY_BY_SOURCE))}
    assert rows[("artifact_submission", "committed", "course")] > 0
    assert rows[("artifact_submission", "draft", "private")] > 0
    assert rows[("attempt", "ungraded", "private")] > 0
    assert rows[("engagement_event", "ungraded", "private")] > 0
    course = {k for k in rows if k[2] != "private"}
    assert course == {("artifact_submission", "committed", "course")}


@db
def test_seeded_outcome_links_reference_course_visible_evidence(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT ev.visibility, count(*) AS n FROM outcome_links o
           JOIN evidence ev ON ev.id = o.evidence_id GROUP BY 1"""
    ))
    assert {r["visibility"]: r["n"] for r in rows} == {
        "course": seeded["provenance"]["outcome_links"]}


@db
def test_reseed_keeps_evidence_visibility(seeded) -> None:  # noqa: ANN001
    before = sorted(map(dict, _run(_fetch(_VISIBILITY_BY_SOURCE))), key=str)

    async def _reseed() -> dict:
        conn = await asyncpg.connect(DB_URL)
        try:
            return await seed(conn, random.Random(42), TEST_PASSWORD)
        finally:
            await conn.close()

    again = _run(_reseed())
    assert again["course_visible_evidence"] == seeded["course_visible_evidence"] > 0
    assert sorted(map(dict, _run(_fetch(_VISIBILITY_BY_SOURCE))), key=str) == before
