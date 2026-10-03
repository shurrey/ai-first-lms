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

from data_mcp.mcp_servers.standards.tools import _analyze_wcag
from data_mcp.seed.all_courses import MissingDemoPasswordError, seed
from data_mcp.seed.cs101 import seed as seed_legacy_cs101
from data_mcp.seed.demo_accounts import fetch_demo_accounts, format_demo_accounts
from data_mcp.seed.scenario_data import ESSAY3_DUE

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
    # The formative seed enrolls Emma in ENG 102 for spec.md §7.9 (§4.3 lists three courses).
    assert accounts["Emma Smith"]["courses"] == "BIO 150, CS 101, ENG 102, MATH 201"
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
    assert again["scenario_data"] == seeded["scenario_data"]
    assert again["formative"] == seeded["formative"]


# ── Provenance history (spec §6.3, §6.6) ──

_PROVENANCE_SNAPSHOT = {
    "ai_actions": """SELECT id, agent, action_type, subject_person, course_node, target_type,
                            sources, model, prompt_sha256, output, created_at
                     FROM ai_actions ORDER BY id""",
    "human_decisions": """SELECT id, ai_action_id, decided_by, decision, diff, reason, decided_at
                          FROM human_decisions ORDER BY id""",
    # evidence ids come from the DB default, so compare the link by its content.
    "outcome_links": """SELECT ai_action_id, delta, observed_at FROM outcome_links
                        ORDER BY ai_action_id, observed_at, delta::text""",
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
    assert by_course == {
        "cs101": expected | {"criterion_feedback"},
        "eng102": expected | {"criterion_feedback", "practice_item"},
    }
    seeded_totals = {k: seeded["provenance"][k] + seeded["formative"][k]
                     for k in ("ai_actions", "human_decisions", "outcome_links")}
    assert seeded_totals["ai_actions"] == sum(r["n"] for r in rows)
    totals = _run(_fetch(
        """SELECT (SELECT count(*) FROM human_decisions) AS d,
                  (SELECT count(*) FROM outcome_links) AS o,
                  (SELECT count(DISTINCT ai_action_id) FROM human_decisions) AS decided,
                  (SELECT count(*) FROM ai_actions) AS a"""
    ))[0]
    assert totals["d"] == seeded_totals["human_decisions"]
    assert totals["o"] == seeded_totals["outcome_links"] > seeded["formative"]["outcome_links"]
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
          AND (ev.payload->>'submission_id' IS NULL OR s.id::text = ev.payload->>'submission_id')
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
    """Grade outcomes cite only course evidence; a revision's per-criterion delta cites the
    learner's own revision, which stays private until its grade is committed (§12.5)."""
    rows = _run(_fetch(
        """SELECT a.action_type, ev.visibility, count(*) AS n FROM outcome_links o
           JOIN ai_actions a ON a.id = o.ai_action_id
           JOIN evidence ev ON ev.id = o.evidence_id GROUP BY 1, 2"""
    ))
    counts = {(r["action_type"], r["visibility"]): r["n"] for r in rows}
    assert counts[("grade_draft", "course")] == seeded["provenance"]["outcome_links"]
    assert set(counts) == {("grade_draft", "course"), ("criterion_feedback", "private"),
                           ("criterion_feedback", "course")}
    assert sum(n for (t, _), n in counts.items() if t == "criterion_feedback") == (
        seeded["formative"]["outcome_links"])


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


# ── Data the demo scenarios read ──

@db
def test_essay3_is_ready_to_grade_in_cs101(seeded) -> None:  # noqa: ANN001
    cs101 = seeded["course_ids"]["cs101"]
    assignment = _run(_fetch(
        """SELECT id, title, metadata FROM nodes
           WHERE kind = 'assessment_item' AND title LIKE 'Essay 3%'
             AND metadata->>'course_id' = $1""",
        cs101,
    ))
    assert len(assignment) == 1
    meta = json.loads(assignment[0]["metadata"])
    assert str(assignment[0]["id"]) == seeded["scenario_data"]["essay3_assignment_id"]
    assert meta["rubric_id"] == seeded["scenario_data"]["essay3_rubric_id"]
    assert meta["due_at"] < "2026-10-02"

    rubric = _run(_fetch(
        """SELECT r.metadata, p.email FROM rubrics r JOIN persons p ON p.id = r.owner_id
           WHERE r.id = $1""",
        uuid.UUID(meta["rubric_id"]),
    ))
    assert rubric[0]["email"] == "m.torres@university.edu"
    assert json.loads(rubric[0]["metadata"])["assignment_node"] == str(assignment[0]["id"])
    criteria = _run(_fetch(
        "SELECT key, levels FROM rubric_criteria WHERE rubric_id = $1 ORDER BY key",
        uuid.UUID(meta["rubric_id"]),
    ))
    assert [c["key"] for c in criteria] == ["analysis", "evidence", "thesis", "writing_mechanics"]
    assert all([lv["score"] for lv in json.loads(c["levels"])] == [1, 2, 3, 4] for c in criteria)

    subs = _run(_fetch(
        """SELECT s.status, s.version, s.parent_id, s.body_md, s.submitted_at, s.course_node,
                  EXISTS (SELECT 1 FROM enrollments e WHERE e.person_id = s.person_id
                          AND e.course_node = $2 AND e.role = 'student') AS enrolled
           FROM submissions s WHERE s.assignment_node = $1""",
        assignment[0]["id"], uuid.UUID(cs101),
    ))
    finals = [s for s in subs if s["status"] == "final"]
    assert len(finals) >= 5
    assert all(s["enrolled"] and str(s["course_node"]) == cs101 for s in subs)
    assert all(len(s["body_md"]) > 300 and s["submitted_at"] <= ESSAY3_DUE for s in finals)
    assert any(s["version"] == 2 and s["parent_id"] for s in finals)


@db
def test_essay3_history_lists_rubric_criteria(seeded) -> None:  # noqa: ANN001
    from mcp.types import CallToolRequest

    from data_mcp.mcp_base import create_mcp_server
    from data_mcp.mcp_servers.assessments.tools import get_tools

    async def _history() -> dict:
        pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
        try:
            person = await pool.fetchval(
                "SELECT person_id FROM submissions WHERE version = 2 AND assignment_node = $1",
                uuid.UUID(seeded["scenario_data"]["essay3_assignment_id"]),
            )
            server = create_mcp_server("assessments", get_tools(pool))
            result = await server.request_handlers[CallToolRequest](CallToolRequest(
                method="tools/call",
                params={"name": "assessments.list_submission_history", "arguments": {
                    "person_id": str(person),
                    "assignment_node": seeded["scenario_data"]["essay3_assignment_id"],
                }},
            ))
            return json.loads(result.root.content[0].text)
        finally:
            await pool.close()

    subs = _run(_history())["submissions"]
    assert [(s["version"], s["status"]) for s in subs] == [(2, "final"), (1, "draft")]
    assert sorted(c["key"] for c in subs[0]["criteria"]) == [
        "analysis", "evidence", "thesis", "writing_mechanics",
    ]


@db
def test_bio150_content_has_wcag_failures_and_passes(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT ci.body_md FROM content_items ci JOIN nodes m ON m.id = ci.node_id
           WHERE m.kind = 'module' AND m.metadata->>'course_id' = $1""",
        seeded["course_ids"]["bio150"],
    ))
    failing: dict[str, int] = {}
    compliant = 0
    for r in rows:
        fails = [f["criterion"] for f in _analyze_wcag(r["body_md"], "AA") if f["status"] == "fail"]
        compliant += not fails
        for criterion in fails:
            failing[criterion] = failing.get(criterion, 0) + 1
    assert set(failing) == {"1.1.1", "1.3.1", "2.4.4"}
    assert compliant > 0


@db
def test_module_content_is_findable_by_chapter_and_topic(seeded) -> None:  # noqa: ANN001
    chapter5 = _run(_fetch(
        """SELECT m.title FROM content_items ci JOIN nodes m ON m.id = ci.node_id
           WHERE ci.body_md ILIKE '%Chapter 5:%' AND m.metadata->>'course_id' = $1""",
        seeded["course_ids"]["cs101"],
    ))
    assert {r["title"] for r in chapter5} == {"Recursion"}
    photosynthesis = _run(_fetch(
        """SELECT count(*) AS n FROM content_items ci JOIN nodes m ON m.id = ci.node_id
           WHERE m.title = 'Photosynthesis' AND ci.body_md ILIKE '%Calvin cycle%'
             AND m.metadata->>'course_id' = $1""",
        seeded["course_ids"]["bio150"],
    ))
    assert photosynthesis[0]["n"] == 3


@db
def test_every_seeded_node_has_an_embedding(seeded) -> None:  # noqa: ANN001
    missing = _run(_fetch("SELECT count(*) AS n FROM nodes WHERE embedding IS NULL"))
    assert seeded["embedded_nodes"] > 0
    assert missing[0]["n"] == 0


@db
def test_engagement_continues_through_october(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT count(DISTINCT ev.person_id) AS students, max(ev.observed_at) AS last
           FROM evidence ev JOIN nodes n ON n.id = ev.node_id
           WHERE ev.kind = 'engagement_event' AND n.metadata->>'course_id' = $1
             AND ev.observed_at >= '2026-10-01' AND ev.observed_at < '2026-10-15'""",
        seeded["course_ids"]["cs101"],
    ))
    assert rows[0]["students"] >= 25
    assert seeded["scenario_data"]["october_engagement_events"] > 0


# ── Formative loop (spec.md §7.8) ──

async def _tool(name: str, args: dict, server_name: str = "assessments") -> dict:
    from mcp.types import CallToolRequest

    from data_mcp.mcp_base import create_mcp_server
    from data_mcp.mcp_servers.assessments.tools import get_tools as assessments_tools
    from data_mcp.mcp_servers.content.tools import get_tools as content_tools

    tools = assessments_tools if server_name == "assessments" else content_tools
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
    try:
        server = create_mcp_server(server_name, tools(pool))
        result = await server.request_handlers[CallToolRequest](CallToolRequest(
            method="tools/call", params={"name": name, "arguments": args}))
        return json.loads(result.root.content[0].text)
    finally:
        await pool.close()


def _person_id(email: str) -> str:
    return str(_run(_fetch("SELECT id FROM persons WHERE email = $1", email))[0]["id"])


@db
def test_every_v1_rubric_criterion_has_a_rubric_criteria_row(seeded) -> None:  # noqa: ANN001
    missing = _run(_fetch(
        """SELECT r.id, c->>'name' AS name FROM rubrics r,
                  jsonb_array_elements(r.criteria) c
           WHERE NOT EXISTS (
             SELECT 1 FROM rubric_criteria rc WHERE rc.rubric_id = r.id
               AND rc.key = COALESCE(c->>'key',
                   btrim(regexp_replace(lower(c->>'name'), '[^a-z0-9]+', '_', 'g'), '_')))"""
    ))
    assert missing == []
    assert seeded["rubric_criteria_backfilled"] > 0


@db
def test_eng102_essay_rubric_is_aligned_to_eng102_outcomes(seeded) -> None:  # noqa: ANN001
    formative = seeded["formative"]
    rows = _run(_fetch(
        """SELECT rc.key, o.title, o.metadata->>'course_id' AS course
           FROM rubric_criteria rc JOIN nodes o ON o.id = ANY(rc.outcome_nodes)
           WHERE rc.rubric_id = $1 ORDER BY rc.key""",
        uuid.UUID(formative["eng102_rubric_id"]),
    ))
    assert [r["key"] for r in rows] == ["analysis", "evidence", "thesis", "writing_mechanics"]
    assert {r["course"] for r in rows} == {seeded["course_ids"]["eng102"]}
    cs_keys = _run(_fetch(
        "SELECT key FROM rubric_criteria WHERE rubric_id = $1 ORDER BY key",
        uuid.UUID(formative["cs101_rubric_id"]),
    ))
    assert [r["key"] for r in cs_keys] == ["correctness", "decomposition", "explanation", "style"]
    syllabi = _run(_fetch(
        """SELECT n.metadata->>'slug' AS slug
           FROM content_items ci JOIN nodes n ON n.id = ci.node_id
           WHERE ci.kind = 'syllabus' ORDER BY 1"""
    ))
    assert [r["slug"] for r in syllabi] == ["cs101", "eng102"]


@db
def test_unreleased_drafts_have_no_evidence(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT s.id FROM submissions s
           WHERE s.status = 'draft'
             AND EXISTS (SELECT 1 FROM criterion_scores cs WHERE cs.submission_id = s.id)
             AND NOT EXISTS (SELECT 1 FROM criterion_scores cs
                             WHERE cs.submission_id = s.id AND cs.released_at IS NOT NULL)
             AND EXISTS (SELECT 1 FROM evidence ev
                         WHERE ev.payload->>'submission_id' = s.id::text)"""
    ))
    assert rows == []


@db
def test_uncommitted_finals_have_no_evidence(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT s.id FROM submissions s
           WHERE s.status = 'final'
             AND NOT EXISTS (SELECT 1 FROM grades g
                             WHERE g.submission_id = s.id AND NOT g.is_draft)
             AND EXISTS (SELECT 1 FROM evidence ev
                         WHERE ev.payload->>'submission_id' = s.id::text)"""
    ))
    assert rows == []


@db
def test_revision_links_cite_only_scores_the_learner_has_seen(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT cs.released_at IS NOT NULL
                  OR EXISTS (SELECT 1 FROM grades g
                             WHERE g.submission_id = s.id AND NOT g.is_draft) AS visible,
                  count(*) AS n
           FROM outcome_links o
           JOIN submissions s ON s.id::text = o.delta->>'submission_id'
           JOIN criterion_scores cs ON cs.submission_id = s.id
                AND cs.criterion_id::text = o.delta->>'criterion_id'
           GROUP BY 1"""
    ))
    assert {r["visible"]: r["n"] for r in rows} == {True: seeded["formative"]["outcome_links"]}


@db
def test_revision_links_carry_the_scores_the_learner_sees(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT o.delta, COALESCE(cs.final_score, cs.ai_score) AS shown,
                  COALESCE(ps.final_score, ps.ai_score) AS shown_before
           FROM outcome_links o
           JOIN criterion_scores cs ON cs.submission_id::text = o.delta->>'submission_id'
                AND cs.criterion_id::text = o.delta->>'criterion_id'
           JOIN criterion_scores ps ON ps.submission_id::text = o.delta->>'parent_id'
                AND ps.criterion_id::text = o.delta->>'criterion_id'"""
    ))
    assert len(rows) == seeded["formative"]["outcome_links"]
    wrong = []
    for r in rows:
        d = json.loads(r["delta"]) if isinstance(r["delta"], str) else r["delta"]
        if (d["after"], d["before"], d["delta"]) != (
                r["shown"], r["shown_before"], r["shown"] - r["shown_before"]):
            wrong.append(d)
    assert wrong == []


@db
def test_emmas_eng102_draft_is_not_dated_in_the_future(seeded) -> None:  # noqa: ANN001
    submitted = _run(_fetch(
        "SELECT submitted_at FROM submissions WHERE person_id = $1 AND assignment_node = $2",
        uuid.UUID(_person_id("emma.smith@student.edu")),
        uuid.UUID(seeded["formative"]["eng102_assignment_id"]),
    ))
    assert [s["submitted_at"].date().isoformat() < "2026-10-03" for s in submitted] == [True]


@db
def test_eng102_histories_show_improvement_plateau_and_regression(seeded) -> None:  # noqa: ANN001
    chains = _run(_fetch(
        """SELECT person_id, array_agg(status || version ORDER BY version) AS versions
           FROM submissions WHERE assignment_node = $1 GROUP BY person_id""",
        uuid.UUID(seeded["formative"]["eng102_assignment_id"]),
    ))
    full = [c for c in chains if c["versions"] == ["draft1", "draft2", "final3"]]
    assert len(full) == 10
    result = _run(_tool("assessments.get_improvement", {
        "course_id": seeded["course_ids"]["eng102"],
        "requester_id": _person_id("e.watson@university.edu"),
    }))
    assert result["view"] == "detail"
    flags = {t["flag"] for s in result["students"] for t in s["trajectories"]}
    assert {"plateaued", "regressed"} <= flags
    improved = [t for s in result["students"] for t in s["trajectories"]
                if t["delta"] is not None and t["delta"] > 0]
    assert improved


@db
def test_seeded_plateau_student_has_an_evidence_weakness_and_private_practice(
    seeded,  # noqa: ANN001
) -> None:
    practice = seeded["formative"]["practice_set_id"]
    student = _run(_fetch("SELECT subject_person FROM ai_actions WHERE id = $1",
                          uuid.UUID(practice)))[0]["subject_person"]
    result = _run(_tool("assessments.weaknesses", {
        "student_id": str(student), "course_id": seeded["course_ids"]["eng102"]}))
    assert "evidence" in [w["key"] for w in result["weaknesses"]]
    attempts = _run(_fetch(
        "SELECT visibility FROM evidence WHERE payload->>'practice_set_id' = $1", practice))
    assert attempts and {a["visibility"] for a in attempts} == {"private"}


@db
def test_emma_has_an_eng102_draft_awaiting_dr_watsons_release(seeded) -> None:  # noqa: ANN001
    emma = _person_id("emma.smith@student.edu")
    subs = _run(_fetch(
        "SELECT status, version FROM submissions WHERE person_id = $1 AND assignment_node = $2",
        uuid.UUID(emma), uuid.UUID(seeded["formative"]["eng102_assignment_id"]),
    ))
    assert [(s["status"], s["version"]) for s in subs] == [("draft", 1)]
    args = {"person_id": emma, "assignment_node": seeded["formative"]["eng102_assignment_id"]}
    mine = _run(_tool("assessments.list_submission_history",
                      {**args, "requester_id": emma}))["submissions"][0]
    assert mine["feedback_status"] == "awaiting_release"
    assert all(c["ai_score"] is None for c in mine["criteria"])
    staff = _run(_tool("assessments.list_submission_history", {
        **args, "requester_id": _person_id("e.watson@university.edu")}))["submissions"][0]
    evidence = next(c for c in staff["criteria"] if c["key"] == "evidence")
    assert evidence["ai_score"] == 2
    assert evidence["ai_evidence_spans"] and evidence["next_step"]


@db
def test_cs101_drafts_cover_every_feedback_state(seeded) -> None:  # noqa: ANN001
    result = _run(_tool("assessments.list_submission_history", {
        "assignment_node": seeded["formative"]["cs101_assignment_id"],
        "course_id": seeded["course_ids"]["cs101"],
        "requester_id": _person_id("m.torres@university.edu")}))
    states = sorted(s["feedback_status"] for s in result["submissions"])
    assert states == ["awaiting_release", "awaiting_release", "pending", "released"]


@db
def test_committed_formative_grades_derive_from_final_scores(seeded) -> None:  # noqa: ANN001
    from data_mcp.rubric_criteria import GRADE_SCORES_SQL

    async def _check() -> list[tuple[dict, dict]]:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                """SELECT g.submission_id, g.scores FROM grades g
                   JOIN submissions s ON s.id = g.submission_id
                   WHERE s.assignment_node = $1 AND NOT g.is_draft""",
                uuid.UUID(seeded["formative"]["eng102_assignment_id"]),
            )
            return [(json.loads(r["scores"]),
                     json.loads(await conn.fetchval(GRADE_SCORES_SQL, r["submission_id"])))
                    for r in rows]
        finally:
            await conn.close()

    pairs = _run(_check())
    assert len(pairs) == 7 and all(stored == derived for stored, derived in pairs)


@db
def test_only_committed_final_criterion_scores_are_course_visible(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT ev.visibility, ev.criterion_score_id IS NOT NULL AS scored,
                  cs.final_score IS NOT NULL AS committed, count(*) AS n
           FROM evidence ev
           JOIN submissions s ON s.id::text = ev.payload->>'submission_id'
           LEFT JOIN criterion_scores cs ON cs.id = ev.criterion_score_id
           WHERE s.assignment_node = ANY($1::uuid[])
           GROUP BY 1, 2, 3""",
        [uuid.UUID(seeded["formative"]["eng102_assignment_id"]),
         uuid.UUID(seeded["formative"]["cs101_assignment_id"])],
    ))
    groups = {(r["visibility"], r["scored"], r["committed"]) for r in rows}
    assert groups == {("course", True, True), ("private", False, False)}


@db
def test_seeded_practice_sets_list_their_items(seeded) -> None:  # noqa: ANN001
    rows = _run(_fetch(
        """SELECT a.output, (SELECT json_object_agg(q.id, q.stem) FROM questions q
                             WHERE q.metadata->>'practice_set_id' = a.id::text) AS stems
           FROM ai_actions a WHERE a.action_type = 'practice_item'"""
    ))
    assert rows
    for r in rows:
        output = json.loads(r["output"]) if isinstance(r["output"], str) else r["output"]
        items = output["items"]
        stems = json.loads(r["stems"])
        assert [i["stem"] for i in items] == [stems[q] for q in output["question_ids"]]
        assert all(i["type"] and i["answer_key"] for i in items)
