"""Contract tests for the roster MCP server tools."""
from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.roster.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("roster", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    async with pool.acquire() as conn:
        student = await conn.fetchrow("SELECT id FROM persons WHERE roles @> '{student}' LIMIT 1")
        faculty = await conn.fetchrow("SELECT id FROM persons WHERE roles @> '{faculty}' LIMIT 1")
        course = await conn.fetchrow("SELECT course_id FROM courses LIMIT 1")
    return {
        "student_id": str(student["id"]) if student else None,
        "faculty_id": str(faculty["id"]) if faculty else None,
        "course_id": str(course["course_id"]) if course else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


async def test_roster_get(server, seeded_ids) -> None:
    result = await _call(server, "roster.get", {"person_id": seeded_ids["student_id"]})
    assert "id" in result
    assert "display_name" in result
    assert "roles" in result
    assert "student" in result["roles"]


async def test_roster_get_not_found(server) -> None:
    result = await _call(server, "roster.get", {"person_id": str(uuid.uuid4())})
    assert "error" in result


async def test_roster_get_student(server, seeded_ids) -> None:
    result = await _call(server, "roster.get_student", {
        "person_id": seeded_ids["student_id"],
        "course_id": seeded_ids["course_id"],
    })
    assert "id" in result
    assert "enrollment" in result
    assert result["enrollment"]["role"] == "student"


async def test_roster_get_student_context(server, seeded_ids) -> None:
    result = await _call(server, "roster.get_student_context", {
        "person_id": seeded_ids["student_id"],
        "course_id": seeded_ids["course_id"],
    })
    assert "recent_evidence" in result
    assert "current_modules" in result
    assert "upcoming_assignments" in result
    assert len(result["current_modules"]) == 12


async def test_roster_list_by_course(server, seeded_ids) -> None:
    result = await _call(server, "roster.list_by_course", {"course_id": seeded_ids["course_id"]})
    assert "persons" in result
    assert len(result["persons"]) >= 50  # at least 50 students


async def test_roster_list_by_course_role_filter(server, seeded_ids) -> None:
    result = await _call(server, "roster.list_by_course", {
        "course_id": seeded_ids["course_id"],
        "role": "faculty",
    })
    assert "persons" in result
    assert len(result["persons"]) == 2  # Dr. Torres and Prof. Lee
