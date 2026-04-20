"""Contract tests for the SIS MCP server tools."""
from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.sis.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("sis", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    """Get IDs from the seeded CS 101 data."""
    async with pool.acquire() as conn:
        student = await conn.fetchrow(
            "SELECT id FROM persons WHERE roles @> '{student}' LIMIT 1"
        )
        course = await conn.fetchrow(
            "SELECT id AS course_id FROM nodes WHERE kind = 'course' LIMIT 1"
        )
    return {
        "student_id": str(student["id"]) if student else None,
        "course_id": str(course["course_id"]) if course else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    text = result.root.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # MCP framework emits plain-text validation errors for missing required props
        return {"error": text}


# ---------------------------------------------------------------------------
# sis.get_transcript
# ---------------------------------------------------------------------------

async def test_get_transcript_returns_structure(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.get_transcript", {"student_id": seeded_ids["student_id"]})
    assert "courses" in result
    assert "gpa" in result
    assert "credits_earned" in result
    assert isinstance(result["courses"], list)
    assert isinstance(result["gpa"], float)
    assert isinstance(result["credits_earned"], (int, float))


async def test_get_transcript_course_shape(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.get_transcript", {"student_id": seeded_ids["student_id"]})
    for course in result["courses"]:
        assert "term" in course
        assert "title" in course
        assert "grade" in course
        assert "credits" in course


async def test_get_transcript_not_found(server) -> None:
    result = await _call(server, "sis.get_transcript", {"student_id": str(uuid.uuid4())})
    assert "error" in result


async def test_get_transcript_missing_student_id(server) -> None:
    result = await _call(server, "sis.get_transcript", {})
    assert "error" in result


async def test_get_transcript_invalid_uuid(server) -> None:
    result = await _call(server, "sis.get_transcript", {"student_id": "not-a-uuid"})
    assert "error" in result


# ---------------------------------------------------------------------------
# sis.degree_audit
# ---------------------------------------------------------------------------

async def test_degree_audit_returns_structure(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.degree_audit", {"student_id": seeded_ids["student_id"]})
    assert "program" in result
    assert "requirements" in result
    assert "satisfied" in result
    assert "remaining" in result
    assert "projected_graduation" in result


async def test_degree_audit_requirements_shape(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.degree_audit", {"student_id": seeded_ids["student_id"]})
    assert isinstance(result["requirements"], list)
    assert len(result["requirements"]) > 0
    for req in result["requirements"]:
        assert "id" in req
        assert "name" in req
        assert "credits_required" in req
        assert "credits_applied" in req
        assert "satisfied" in req


async def test_degree_audit_with_program_id(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.degree_audit", {
        "student_id": seeded_ids["student_id"],
        "program_id": "CS-MS",
    })
    assert result["program"] == "CS-MS"
    assert "requirements" in result


async def test_degree_audit_not_found(server) -> None:
    result = await _call(server, "sis.degree_audit", {"student_id": str(uuid.uuid4())})
    assert "error" in result


# ---------------------------------------------------------------------------
# sis.check_prerequisites
# ---------------------------------------------------------------------------

async def test_check_prerequisites_returns_ok_bool(server, seeded_ids) -> None:
    if not seeded_ids["student_id"] or not seeded_ids["course_id"]:
        pytest.skip("No seeded data")
    result = await _call(server, "sis.check_prerequisites", {
        "student_id": seeded_ids["student_id"],
        "course_id": seeded_ids["course_id"],
    })
    assert "ok" in result
    assert "missing" in result
    assert isinstance(result["ok"], bool)
    assert isinstance(result["missing"], list)


async def test_check_prerequisites_student_not_found(server, seeded_ids) -> None:
    if not seeded_ids["course_id"]:
        pytest.skip("No seeded courses")
    result = await _call(server, "sis.check_prerequisites", {
        "student_id": str(uuid.uuid4()),
        "course_id": seeded_ids["course_id"],
    })
    assert "error" in result


async def test_check_prerequisites_course_not_found(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.check_prerequisites", {
        "student_id": seeded_ids["student_id"],
        "course_id": str(uuid.uuid4()),
    })
    assert "error" in result


async def test_check_prerequisites_missing_args(server) -> None:
    result = await _call(server, "sis.check_prerequisites", {"student_id": str(uuid.uuid4())})
    assert "error" in result


# ---------------------------------------------------------------------------
# sis.catalog_search
# ---------------------------------------------------------------------------

async def test_catalog_search_no_filters(server) -> None:
    result = await _call(server, "sis.catalog_search", {})
    assert "courses" in result
    assert isinstance(result["courses"], list)


async def test_catalog_search_with_query(server) -> None:
    result = await _call(server, "sis.catalog_search", {"query": "CS"})
    assert "courses" in result
    assert isinstance(result["courses"], list)


async def test_catalog_search_course_shape(server) -> None:
    result = await _call(server, "sis.catalog_search", {})
    for course in result["courses"]:
        assert "id" in course
        assert "title" in course
        assert "description" in course
        assert "credits" in course


async def test_catalog_search_empty_query_returns_all(server) -> None:
    result = await _call(server, "sis.catalog_search", {"query": ""})
    assert "courses" in result
    # The seeded DB has at least one course
    assert len(result["courses"]) >= 1


async def test_catalog_search_nonexistent_subject(server) -> None:
    result = await _call(server, "sis.catalog_search", {"subject": "zzznonexistent"})
    assert "courses" in result
    assert result["courses"] == []


# ---------------------------------------------------------------------------
# sis.schedule_availability
# ---------------------------------------------------------------------------

async def test_schedule_availability_empty_course_ids(server, seeded_ids) -> None:
    if not seeded_ids["student_id"]:
        pytest.skip("No seeded students")
    result = await _call(server, "sis.schedule_availability", {
        "student_id": seeded_ids["student_id"],
        "term": "Fall 2025",
        "course_ids": [],
    })
    assert result["feasible"] is True
    assert result["sections"] == []
    assert result["conflicts"] == []


async def test_schedule_availability_single_course(server, seeded_ids) -> None:
    if not seeded_ids["student_id"] or not seeded_ids["course_id"]:
        pytest.skip("No seeded data")
    result = await _call(server, "sis.schedule_availability", {
        "student_id": seeded_ids["student_id"],
        "term": "Fall 2025",
        "course_ids": [seeded_ids["course_id"]],
    })
    assert "feasible" in result
    assert "sections" in result
    assert "conflicts" in result
    assert isinstance(result["feasible"], bool)
    assert isinstance(result["sections"], list)
    assert isinstance(result["conflicts"], list)


async def test_schedule_availability_section_shape(server, seeded_ids) -> None:
    if not seeded_ids["student_id"] or not seeded_ids["course_id"]:
        pytest.skip("No seeded data")
    result = await _call(server, "sis.schedule_availability", {
        "student_id": seeded_ids["student_id"],
        "term": "Fall 2025",
        "course_ids": [seeded_ids["course_id"]],
    })
    for sec in result["sections"]:
        assert "course_id" in sec
        assert "title" in sec
        assert "term" in sec
        assert "schedule" in sec
        assert "already_enrolled" in sec


async def test_schedule_availability_not_found_student(server, seeded_ids) -> None:
    if not seeded_ids["course_id"]:
        pytest.skip("No seeded courses")
    result = await _call(server, "sis.schedule_availability", {
        "student_id": str(uuid.uuid4()),
        "term": "Fall 2025",
        "course_ids": [seeded_ids["course_id"]],
    })
    assert "error" in result


async def test_schedule_availability_missing_required_args(server) -> None:
    result = await _call(server, "sis.schedule_availability", {
        "student_id": str(uuid.uuid4()),
        "course_ids": [],
    })
    assert "error" in result
