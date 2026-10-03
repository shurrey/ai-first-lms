"""Contract tests for the assessments MCP server tools."""
from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.assessments.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("assessments", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    """Get IDs from the seeded CS 101 data."""
    async with pool.acquire() as conn:
        bank = await conn.fetchrow("SELECT id FROM question_banks LIMIT 1")
        submission = await conn.fetchrow("SELECT id, person_id FROM submissions LIMIT 1")
        rubric = await conn.fetchrow("SELECT id FROM rubrics LIMIT 1")
        student = await conn.fetchrow("SELECT id FROM persons WHERE roles @> '{student}' LIMIT 1")
        faculty = await conn.fetchrow("SELECT id FROM persons WHERE roles @> '{faculty}' LIMIT 1")

    return {
        "bank_id": str(bank["id"]) if bank else None,
        "submission_id": str(submission["id"]) if submission else None,
        "submission_person_id": str(submission["person_id"]) if submission else None,
        "rubric_id": str(rubric["id"]) if rubric else None,
        "student_id": str(student["id"]) if student else None,
        "faculty_id": str(faculty["id"]) if faculty else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


# ── search_bank ─────────────────────────────────────────────────────────────

async def test_search_bank_all(server, seeded_ids) -> None:
    if not seeded_ids["bank_id"]:
        pytest.skip("No seeded question bank")
    result = await _call(server, "assessments.search_bank", {"bank_id": seeded_ids["bank_id"]})
    assert "questions" in result
    assert isinstance(result["questions"], list)
    assert len(result["questions"]) > 0


async def test_search_bank_by_query(server, seeded_ids) -> None:
    if not seeded_ids["bank_id"]:
        pytest.skip("No seeded question bank")
    result = await _call(server, "assessments.search_bank", {
        "bank_id": seeded_ids["bank_id"],
        "query": "What",
    })
    assert "questions" in result
    assert isinstance(result["questions"], list)


async def test_search_bank_no_filters(server) -> None:
    result = await _call(server, "assessments.search_bank", {})
    assert "questions" in result
    assert isinstance(result["questions"], list)


# ── create_question ──────────────────────────────────────────────────────────

async def test_create_question(server, seeded_ids) -> None:
    if not seeded_ids["bank_id"]:
        pytest.skip("No seeded question bank")
    result = await _call(server, "assessments.create_question", {
        "bank_id": seeded_ids["bank_id"],
        "type": "mcq",
        "stem": "Which keyword is used to define a function in Python?",
        "options": {"A": "func", "B": "def", "C": "function", "D": "define"},
        "answer_key": {"correct": "B"},
        "bloom_level": "remember",
        "difficulty": "easy",
        "aligned_nodes": [],
    })
    assert "question_id" in result
    # Verify it's a valid UUID
    uuid.UUID(result["question_id"])


async def test_create_question_invalid_bank(server) -> None:
    result = await _call(server, "assessments.create_question", {
        "bank_id": str(uuid.uuid4()),
        "type": "short_answer",
        "stem": "Explain recursion.",
        "answer_key": {"rubric": "mentions base case and recursive case"},
    })
    assert "error" in result


# ── get_submission ───────────────────────────────────────────────────────────

async def test_get_submission(server, seeded_ids) -> None:
    if not seeded_ids["submission_id"]:
        pytest.skip("No seeded submission")
    result = await _call(server, "assessments.get_submission", {
        "submission_id": seeded_ids["submission_id"],
    })
    assert "id" in result
    assert "person_id" in result
    assert "assignment_node" in result
    assert "body_md" in result
    assert "attachments" in result
    assert "submitted_at" in result


async def test_get_submission_not_found(server) -> None:
    result = await _call(server, "assessments.get_submission", {
        "submission_id": str(uuid.uuid4()),
    })
    assert "error" in result


# ── get_rubric ───────────────────────────────────────────────────────────────

async def test_get_rubric(server, seeded_ids) -> None:
    if not seeded_ids["rubric_id"]:
        pytest.skip("No seeded rubric")
    result = await _call(server, "assessments.get_rubric", {
        "rubric_id": seeded_ids["rubric_id"],
    })
    assert "id" in result
    assert "title" in result
    assert "criteria" in result
    assert isinstance(result["criteria"], list)


async def test_get_rubric_not_found(server) -> None:
    result = await _call(server, "assessments.get_rubric", {
        "rubric_id": str(uuid.uuid4()),
    })
    assert "error" in result


# ── draft_grade + commit_grade ───────────────────────────────────────────────

async def test_draft_grade(server, seeded_ids) -> None:
    if not seeded_ids["submission_id"] or not seeded_ids["faculty_id"]:
        pytest.skip("Missing seeded submission or faculty")
    result = await _call(server, "assessments.draft_grade", {
        "submission_id": seeded_ids["submission_id"],
        "rubric_id": seeded_ids["rubric_id"],
        "scores": {"Correctness": 35, "Style": 18, "Explanation": 24},
        "feedback": {"Correctness": "Good work", "Style": "Clean code", "Explanation": "Well explained"},
        "holistic_md": "Strong submission overall.",
        "graded_by": seeded_ids["faculty_id"],
    })
    assert "grade_id" in result
    uuid.UUID(result["grade_id"])


async def test_draft_grade_invalid_submission(server, seeded_ids) -> None:
    if not seeded_ids["faculty_id"]:
        pytest.skip("No seeded faculty")
    result = await _call(server, "assessments.draft_grade", {
        "submission_id": str(uuid.uuid4()),
        "scores": {"total": 90},
        "feedback": {"general": "Good"},
        "graded_by": seeded_ids["faculty_id"],
    })
    assert "error" in result


async def test_commit_grade(server, seeded_ids) -> None:
    """Create a draft grade then commit it."""
    if not seeded_ids["submission_id"] or not seeded_ids["faculty_id"]:
        pytest.skip("Missing seeded submission or faculty")
    # First create a fresh draft grade to commit
    draft_result = await _call(server, "assessments.draft_grade", {
        "submission_id": seeded_ids["submission_id"],
        "scores": {"total": 88},
        "feedback": {"general": "Well done"},
        "holistic_md": "Good overall effort.",
        "graded_by": seeded_ids["faculty_id"],
    })
    assert "grade_id" in draft_result

    # Now commit it
    commit_result = await _call(server, "assessments.commit_grade", {
        "grade_id": draft_result["grade_id"],
    })
    assert commit_result.get("committed") is True
    assert "committed_at" in commit_result


async def test_commit_grade_not_found(server) -> None:
    result = await _call(server, "assessments.commit_grade", {
        "grade_id": str(uuid.uuid4()),
    })
    assert "error" in result


async def test_commit_grade_already_committed(server, seeded_ids) -> None:
    """Committing an already-committed grade returns an error."""
    if not seeded_ids["submission_id"] or not seeded_ids["faculty_id"]:
        pytest.skip("Missing seeded submission or faculty")
    draft_result = await _call(server, "assessments.draft_grade", {
        "submission_id": seeded_ids["submission_id"],
        "scores": {"total": 75},
        "feedback": {"general": "Needs improvement"},
        "graded_by": seeded_ids["faculty_id"],
    })
    grade_id = draft_result["grade_id"]

    # Commit once
    await _call(server, "assessments.commit_grade", {"grade_id": grade_id})
    # Try to commit again
    result = await _call(server, "assessments.commit_grade", {"grade_id": grade_id})
    assert "error" in result


# ── list_recent_evidence ─────────────────────────────────────────────────────

async def test_list_recent_evidence(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded student")
    result = await _call(server, "assessments.list_recent_evidence", {
        "person_id": seeded_ids["student_id"],
        "since_days": 365,
    })
    assert "evidence" in result
    assert isinstance(result["evidence"], list)


async def test_list_recent_evidence_default_window(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded student")
    result = await _call(server, "assessments.list_recent_evidence", {
        "person_id": seeded_ids["student_id"],
    })
    assert "evidence" in result


async def test_list_recent_evidence_with_node_filter(server, seeded_ids, pool) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded student")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT node_id FROM evidence WHERE person_id = $1 LIMIT 1",
            uuid.UUID(seeded_ids["student_id"]),
        )
    if not row:
        pytest.skip("No evidence for this student")

    result = await _call(server, "assessments.list_recent_evidence", {
        "person_id": seeded_ids["student_id"],
        "node_ids": [str(row["node_id"])],
        "since_days": 365,
    })
    assert "evidence" in result
    assert isinstance(result["evidence"], list)
    # All returned evidence must match the requested node
    for ev in result["evidence"]:
        assert ev["node_id"] == str(row["node_id"])


async def test_list_recent_evidence_window_follows_lms_as_of(server, pool, monkeypatch) -> None:
    person, node = uuid.uuid4(), uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, '{student}', 'Clock Test', $2)",
            person, f"clock-{person}@student.edu",
        )
        await conn.execute("INSERT INTO nodes (id, kind, title) VALUES ($1, 'concept', 'clock test')", node)
        for day in ("2026-09-01", "2026-09-20", "2026-10-10"):
            await conn.execute(
                """INSERT INTO evidence (person_id, node_id, kind, source, observed_at)
                   VALUES ($1, $2, 'engagement_event', 'platform', $3::text::timestamptz)""",
                person, node, day,
            )
    monkeypatch.setenv("LMS_AS_OF", "2026-09-25")
    try:
        result = await _call(server, "assessments.list_recent_evidence", {
            "person_id": str(person), "since_days": 10,
        })
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM evidence WHERE person_id = $1", person)
            await conn.execute("DELETE FROM nodes WHERE id = $1", node)
            await conn.execute("DELETE FROM persons WHERE id = $1", person)
    assert [e["observed_at"][:10] for e in result["evidence"]] == ["2026-09-20"]


async def test_list_recent_evidence_breaks_ties_by_node_then_payload(server, pool, monkeypatch) -> None:
    """Rows are inserted in reverse of the expected order, which is the order an untied sort returns."""
    person = uuid.uuid4()
    low, high = sorted((uuid.uuid4(), uuid.uuid4()))
    ids = {}
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, '{student}', 'Tie Test', $2)",
            person, f"tie-{person}@student.edu",
        )
        for node in (low, high):
            await conn.execute("INSERT INTO nodes (id, kind, title) VALUES ($1, 'concept', 'tie')", node)
        for label, node, payload in (("high", high, '{"d": 1}'), ("low2", low, '{"d": 2}'),
                                     ("low1", low, '{"d": 1}')):
            ids[label] = str(await conn.fetchval(
                """INSERT INTO evidence (person_id, node_id, kind, source, observed_at, payload)
                   VALUES ($1, $2, 'engagement_event', 'platform', '2026-09-20T10:00:00Z', $3::jsonb)
                   RETURNING id""",
                person, node, payload,
            ))
    monkeypatch.setenv("LMS_AS_OF", "2026-09-25")
    try:
        result = await _call(server, "assessments.list_recent_evidence", {
            "person_id": str(person), "since_days": 10,
        })
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM evidence WHERE person_id = $1", person)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])", [low, high])
            await conn.execute("DELETE FROM persons WHERE id = $1", person)
    assert [e["id"] for e in result["evidence"]] == [ids["low1"], ids["low2"], ids["high"]]


# ── list_submission_history ──────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def history(pool):
    """One learner's draft and revision on a rubric-linked assignment, plus a submission whose
    course comes only from its assignment's metadata (course_node is NULL, as in older rows)."""
    ids = {k: uuid.uuid4() for k in (
        "student", "other", "course", "assignment", "legacy_assignment", "rubric",
        "thesis", "evidence", "v1", "v2", "legacy", "others_sub",
    )}
    async with pool.acquire() as conn:
        for key in ("student", "other"):
            await conn.execute(
                "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, '{student}', $2, $3)",
                ids[key], f"History {key}", f"history-{ids[key]}@student.edu",
            )
        await conn.execute(
            "INSERT INTO nodes (id, kind, title) VALUES ($1, 'course', 'History Test Course')",
            ids["course"],
        )
        for key, rubric in (("assignment", str(ids["rubric"])), ("legacy_assignment", None)):
            meta = {"course_id": str(ids["course"]), "due_at": "2026-09-25T23:59:00+00:00"}
            if rubric:
                meta["rubric_id"] = rubric
            await conn.execute(
                "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'assessment_item', $2, $3)",
                ids[key], f"History {key}", json.dumps(meta),
            )
        await conn.execute(
            "INSERT INTO rubrics (id, title, criteria) VALUES ($1, 'History rubric', '[]')",
            ids["rubric"],
        )
        for key in ("thesis", "evidence"):
            await conn.execute(
                """INSERT INTO rubric_criteria (id, rubric_id, key, description, levels)
                   VALUES ($1, $2, $3, $3, '[]')""",
                ids[key], ids["rubric"], key,
            )
        rows = [
            ("v1", "student", "assignment", "2026-09-20", 1, None, "draft", ids["course"]),
            ("v2", "student", "assignment", "2026-09-23", 2, ids["v1"], "final", ids["course"]),
            ("legacy", "student", "legacy_assignment", "2026-09-10", 1, None, "final", None),
            ("others_sub", "other", "assignment", "2026-09-24", 1, None, "final", ids["course"]),
        ]
        for sid, person, assignment, at, version, parent, status, course in rows:
            await conn.execute(
                """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at,
                                            version, parent_id, status, course_node)
                   VALUES ($1, $2, $3, 'essay', $4::text::timestamptz, $5, $6, $7, $8)""",
                ids[sid], ids[person], ids[assignment], at, version, parent, status, course,
            )
        await conn.execute(
            "INSERT INTO criterion_scores (submission_id, criterion_id, ai_score) VALUES ($1, $2, 3)",
            ids["v2"], ids["thesis"],
        )
    yield {k: str(v) for k, v in ids.items()}
    async with pool.acquire() as conn:
        subs = [ids[k] for k in ("v2", "v1", "legacy", "others_sub")]
        await conn.execute("DELETE FROM criterion_scores WHERE submission_id = ANY($1::uuid[])", subs)
        for sid in subs:
            await conn.execute("DELETE FROM submissions WHERE id = $1", sid)
        await conn.execute("DELETE FROM rubrics WHERE id = $1", ids["rubric"])
        await conn.execute(
            "DELETE FROM nodes WHERE id = ANY($1::uuid[])",
            [ids["assignment"], ids["legacy_assignment"], ids["course"]],
        )
        await conn.execute(
            "DELETE FROM persons WHERE id = ANY($1::uuid[])", [ids["student"], ids["other"]],
        )


async def test_list_submission_history_by_assignment(server, history) -> None:
    result = await _call(server, "assessments.list_submission_history", {
        "person_id": history["student"], "assignment_node": history["assignment"],
    })
    subs = result["submissions"]
    assert [s["id"] for s in subs] == [history["v2"], history["v1"]]
    v2, v1 = subs
    assert (v2["version"], v2["status"], v2["parent_id"]) == (2, "final", history["v1"])
    assert (v1["version"], v1["status"], v1["parent_id"]) == (1, "draft", None)
    assert v2["assignment_node"] == history["assignment"]
    assert v2["submitted_at"].startswith("2026-09-23")
    assert {c["key"]: (c["ai_score"], c["final_score"], c["released_at"]) for c in v2["criteria"]} == {
        "evidence": (None, None, None), "thesis": (3, None, None),
    }
    assert {c["criterion_id"] for c in v1["criteria"]} == {history["thesis"], history["evidence"]}
    assert all(c["ai_score"] is None for c in v1["criteria"])


async def test_list_submission_history_by_course_includes_rows_without_course_node(
    server, history,
) -> None:
    result = await _call(server, "assessments.list_submission_history", {
        "person_id": history["student"], "course_id": history["course"],
    })
    assert [s["id"] for s in result["submissions"]] == [history["v2"], history["v1"], history["legacy"]]
    assert result["submissions"][2]["criteria"] == []


async def test_list_submission_history_course_filter_excludes_another_courses_work(
    server, pool, history,
) -> None:
    # The same learner in a second course: one row with course_node, one with only the
    # assignment's metadata course_id.
    other_course, other_assignment = uuid.uuid4(), uuid.uuid4()
    subs = [uuid.uuid4(), uuid.uuid4()]
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO nodes (id, kind, title) VALUES ($1, 'course', 'Other')",
                           other_course)
        await conn.execute(
            "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'assessment_item', 'O', $2)",
            other_assignment, json.dumps({"course_id": str(other_course)}))
        for sid, course in zip(subs, (other_course, None), strict=True):
            await conn.execute(
                """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at,
                                            version, status, course_node)
                   VALUES ($1, $2, $3, 'essay', '2026-09-26T00:00:00Z', 1, 'final', $4)""",
                sid, uuid.UUID(history["student"]), other_assignment, course)
    try:
        by_course = await _call(server, "assessments.list_submission_history", {
            "person_id": history["student"], "course_id": history["course"]})
        mismatched = await _call(server, "assessments.list_submission_history", {
            "person_id": history["student"], "assignment_node": str(other_assignment),
            "course_id": history["course"]})
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM submissions WHERE id = ANY($1::uuid[])", subs)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                               [other_assignment, other_course])
    assert [s["id"] for s in by_course["submissions"]] == [
        history["v2"], history["v1"], history["legacy"]]
    assert mismatched["submissions"] == []


async def test_list_submission_history_without_person_lists_every_learner_in_the_course(
    server, history,
) -> None:
    result = await _call(server, "assessments.list_submission_history", {
        "course_id": history["course"],
    })
    subs = result["submissions"]
    assert [s["id"] for s in subs] == [
        history["others_sub"], history["v2"], history["v1"], history["legacy"]]
    assert [(s["person_id"], s["rubric_id"], s["assignment_title"]) for s in subs] == [
        (history["other"], history["rubric"], "History assignment"),
        (history["student"], history["rubric"], "History assignment"),
        (history["student"], history["rubric"], "History assignment"),
        (history["student"], None, "History legacy_assignment"),
    ]


async def test_list_submission_history_without_person_excludes_another_courses_work(
    server, pool, history,
) -> None:
    other_course, other_assignment, sub = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO nodes (id, kind, title) VALUES ($1, 'course', 'Other')",
                           other_course)
        await conn.execute(
            "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'assessment_item', $2, $3)",
            other_assignment, "History assignment",
            json.dumps({"course_id": str(other_course)}))
        await conn.execute(
            """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at,
                                        version, status, course_node)
               VALUES ($1, $2, $3, 'essay', '2026-09-27T00:00:00Z', 1, 'final', $4)""",
            sub, uuid.UUID(history["other"]), other_assignment, other_course)
    try:
        by_course = await _call(server, "assessments.list_submission_history", {
            "course_id": history["course"]})
        by_title = await _call(server, "assessments.list_submission_history", {
            "course_id": history["course"], "assignment_title": "History assignment"})
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM submissions WHERE id = $1", sub)
            await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                               [other_assignment, other_course])
    assert str(sub) not in {s["id"] for s in by_course["submissions"]}
    assert str(sub) not in {s["id"] for s in by_title["submissions"]}
    assert len(by_course["submissions"]) == 4


async def test_list_submission_history_title_filter_is_case_insensitive_substring(
    server, history,
) -> None:
    result = await _call(server, "assessments.list_submission_history", {
        "course_id": history["course"], "assignment_title": "  HISTORY assignment ",
    })
    assert [s["id"] for s in result["submissions"]] == [
        history["others_sub"], history["v2"], history["v1"]]
    assert {s["assignment_node"] for s in result["submissions"]} == {history["assignment"]}


async def test_list_submission_history_limit_keeps_newest(server, history) -> None:
    result = await _call(server, "assessments.list_submission_history", {
        "person_id": history["student"], "course_id": history["course"], "limit": 1,
    })
    assert [s["id"] for s in result["submissions"]] == [history["v2"]]


@pytest.mark.parametrize("args", [
    {},
    {"assignment_node": "not-a-uuid"},
    {"course_id": "00000000-0000-4000-8000-000000000000", "limit": 0},
    {"course_id": "00000000-0000-4000-8000-000000000000", "limit": 101},
    {"course_id": "00000000-0000-4000-8000-000000000000", "assignment_title": " "},
])
async def test_list_submission_history_rejects_bad_arguments(server, history, args) -> None:
    result = await _call(server, "assessments.list_submission_history", {
        "person_id": history["student"], **args,
    })
    assert result["code"] == "validation_error"
    assert result["submissions"] == []
