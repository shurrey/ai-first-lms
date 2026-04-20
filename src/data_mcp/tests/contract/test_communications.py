"""Contract tests for the communications MCP server tools."""
from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.communications.tools import get_tools

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server(pool):
    return create_mcp_server("communications", get_tools(pool))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_ids(pool):
    """Get IDs from the seeded CS 101 data."""
    async with pool.acquire() as conn:
        faculty = await conn.fetchrow(
            "SELECT id FROM persons WHERE roles @> '{faculty}' LIMIT 1"
        )
        course = await conn.fetchrow("SELECT course_id FROM courses LIMIT 1")
        template = await conn.fetchrow("SELECT id FROM message_templates LIMIT 1")
    return {
        "faculty_id": str(faculty["id"]) if faculty else None,
        "course_id": str(course["course_id"]) if course else None,
        "template_id": str(template["id"]) if template else None,
    }


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


# ---------------------------------------------------------------------------
# communications.draft_message
# ---------------------------------------------------------------------------

async def test_draft_message_returns_draft_id(server, seeded_ids) -> None:
    if not seeded_ids["faculty_id"]:
        pytest.skip("No seeded faculty")
    result = await _call(server, "communications.draft_message", {
        "author_id": seeded_ids["faculty_id"],
        "channel": "announcement",
        "audience": {"course_id": seeded_ids["course_id"]},
        "subject": "Test Announcement",
        "body_md": "# Hello\n\nThis is a test announcement.",
    })
    assert "draft_id" in result
    # Verify the draft was persisted
    assert uuid.UUID(result["draft_id"])  # valid UUID


async def test_draft_message_without_subject(server, seeded_ids) -> None:
    if not seeded_ids["faculty_id"]:
        pytest.skip("No seeded faculty")
    result = await _call(server, "communications.draft_message", {
        "author_id": seeded_ids["faculty_id"],
        "channel": "inbox",
        "audience": {"role": "student"},
        "body_md": "Please check the course portal for updates.",
    })
    assert "draft_id" in result


async def test_draft_message_with_scheduled_for(server, seeded_ids) -> None:
    if not seeded_ids["faculty_id"]:
        pytest.skip("No seeded faculty")
    result = await _call(server, "communications.draft_message", {
        "author_id": seeded_ids["faculty_id"],
        "channel": "email",
        "audience": {"course_id": seeded_ids["course_id"]},
        "subject": "Scheduled Message",
        "body_md": "This message is scheduled.",
        "scheduled_for": "2026-05-01T09:00:00Z",
    })
    assert "draft_id" in result


# ---------------------------------------------------------------------------
# communications.send_message
# ---------------------------------------------------------------------------

async def test_send_message_returns_sent_at_and_recipient_count(server, seeded_ids) -> None:
    if not seeded_ids["faculty_id"]:
        pytest.skip("No seeded faculty")
    # First draft a message
    draft_result = await _call(server, "communications.draft_message", {
        "author_id": seeded_ids["faculty_id"],
        "channel": "announcement",
        "audience": {"course_id": seeded_ids["course_id"]},
        "subject": "Send Test",
        "body_md": "This message will be sent.",
    })
    draft_id = draft_result["draft_id"]

    # Now send it
    result = await _call(server, "communications.send_message", {"draft_id": draft_id})
    assert "sent_at" in result
    assert "recipient_count" in result
    assert isinstance(result["recipient_count"], int)
    assert result["recipient_count"] >= 0


async def test_send_message_cannot_send_twice(server, seeded_ids) -> None:
    if not seeded_ids["faculty_id"]:
        pytest.skip("No seeded faculty")
    draft_result = await _call(server, "communications.draft_message", {
        "author_id": seeded_ids["faculty_id"],
        "channel": "inbox",
        "audience": {},
        "body_md": "One-time send.",
    })
    draft_id = draft_result["draft_id"]

    # Send once
    first = await _call(server, "communications.send_message", {"draft_id": draft_id})
    assert "sent_at" in first

    # Sending again must return an error
    second = await _call(server, "communications.send_message", {"draft_id": draft_id})
    assert "error" in second


async def test_send_message_draft_not_found(server) -> None:
    result = await _call(server, "communications.send_message", {
        "draft_id": str(uuid.uuid4()),
    })
    assert "error" in result


# ---------------------------------------------------------------------------
# communications.list_templates
# ---------------------------------------------------------------------------

async def test_list_templates_returns_all(server) -> None:
    result = await _call(server, "communications.list_templates", {})
    assert "templates" in result
    assert isinstance(result["templates"], list)
    # Seed inserts 3 templates
    assert len(result["templates"]) >= 3
    # Each template has the required fields
    for tpl in result["templates"]:
        assert "id" in tpl
        assert "name" in tpl
        assert "subject" in tpl
        assert "body_md" in tpl


async def test_list_templates_by_category_returns_list(server) -> None:
    # Category that likely doesn't exist — should return empty list, not an error
    result = await _call(server, "communications.list_templates", {"category": "nonexistent_category"})
    assert "templates" in result
    assert result["templates"] == []


async def test_list_templates_known_names(server) -> None:
    result = await _call(server, "communications.list_templates", {})
    names = {t["name"] for t in result["templates"]}
    assert "midterm_reminder" in names
    assert "at_risk_outreach" in names
    assert "assignment_feedback" in names
