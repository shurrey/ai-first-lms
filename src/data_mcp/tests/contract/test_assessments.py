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
