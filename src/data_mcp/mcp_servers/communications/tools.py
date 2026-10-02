"""Communications MCP server tool handlers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef

# Email delivery is out of scope this round (spec.md §0.4); only in-app channels send.
SENDABLE_CHANNELS = ("inbox", "announcement")


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all communications server tool definitions."""

    async def draft_message(args: dict[str, Any]) -> dict[str, Any]:
        author_id = args["author_id"]
        channel = args["channel"]
        audience = args["audience"]
        subject = args.get("subject")
        body_md = args["body_md"]
        scheduled_for_raw = args.get("scheduled_for")

        scheduled_for = None
        if scheduled_for_raw:
            if isinstance(scheduled_for_raw, str):
                scheduled_for = datetime.fromisoformat(scheduled_for_raw.replace("Z", "+00:00"))
            else:
                scheduled_for = scheduled_for_raw

        # audience may arrive as a dict or a JSON string
        if isinstance(audience, str):
            audience_json = audience
        else:
            audience_json = json.dumps(audience)

        async with pool.acquire() as conn:
            draft_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO messages
                       (id, author_id, channel, audience, subject, body_md,
                        is_draft, scheduled_for)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, true, $7)""",
                draft_id,
                uuid.UUID(author_id),
                channel,
                audience_json,
                subject,
                body_md,
                scheduled_for,
            )
            return {"draft_id": str(draft_id)}

    async def send_message(args: dict[str, Any]) -> dict[str, Any]:
        draft_id = args["draft_id"]

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, channel, audience, is_draft FROM messages WHERE id = $1",
                uuid.UUID(draft_id),
            )
            if not row:
                return {"error": "Draft not found"}
            if not row["is_draft"]:
                return {"error": "Message already sent"}
            if row["channel"] not in SENDABLE_CHANNELS:
                return {
                    "error": f"Channel {row['channel']!r} cannot be sent; "
                    "only inbox and announcement messages are delivered."
                }

            sent_at = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE messages SET is_draft = false, sent_at = $1 WHERE id = $2",
                sent_at,
                uuid.UUID(draft_id),
            )

            # Count recipients from audience jsonb
            audience = row["audience"]
            if isinstance(audience, str):
                audience = json.loads(audience)

            recipient_count = 0
            if isinstance(audience, dict):
                # audience may be {course_id: ..., role: ...} — count matching persons
                course_id = audience.get("course_id")
                role = audience.get("role")
                person_ids = audience.get("person_ids")

                if person_ids:
                    recipient_count = len(person_ids)
                elif course_id or role:
                    count_row = await conn.fetchrow(
                        """SELECT COUNT(*) FROM persons p
                           WHERE ($1::uuid IS NULL OR EXISTS (
                                     SELECT 1 FROM enrollments e
                                     WHERE e.person_id = p.id AND e.course_node = $1))
                             AND ($2::text IS NULL OR p.roles @> ARRAY[$2::text])""",
                        str(course_id) if course_id else None,
                        role or None,
                    )
                    recipient_count = count_row["count"] if count_row else 0
                else:
                    # Broadcast — count all active persons
                    count_row = await conn.fetchrow("SELECT COUNT(*) FROM persons")
                    recipient_count = count_row["count"] if count_row else 0
            elif isinstance(audience, list):
                recipient_count = len(audience)

            return {
                "sent_at": sent_at.isoformat(),
                "recipient_count": int(recipient_count),
            }

    async def list_templates(args: dict[str, Any]) -> dict[str, Any]:
        category = args.get("category")

        async with pool.acquire() as conn:
            if category:
                rows = await conn.fetch(
                    """SELECT id, name, subject, body_md
                       FROM message_templates
                       WHERE metadata->>'category' = $1
                       ORDER BY name""",
                    category,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, name, subject, body_md
                       FROM message_templates
                       ORDER BY name""",
                )
            return {
                "templates": [
                    {
                        "id": str(r["id"]),
                        "name": r["name"],
                        "subject": r["subject"] or "",
                        "body_md": r["body_md"],
                    }
                    for r in rows
                ]
            }

    return [
        ToolDef(
            name="communications.draft_message",
            description="Create a draft message for later review and sending",
            input_schema={
                "type": "object",
                "properties": {
                    "author_id": {"type": "string"},
                    "channel": {"type": "string"},
                    "audience": {"type": ["object", "string"]},
                    "subject": {"type": "string"},
                    "body_md": {"type": "string"},
                    "scheduled_for": {"type": "string"},
                },
                "required": ["author_id", "channel", "audience", "body_md"],
            },
            handler=draft_message,
            mutates=True,
        ),
        ToolDef(
            name="communications.send_message",
            description="Send a previously drafted message (requires approval)",
            input_schema={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                },
                "required": ["draft_id"],
            },
            handler=send_message,
            mutates=True,
            requires_approval=True,
        ),
        ToolDef(
            name="communications.list_templates",
            description="List available message templates, optionally filtered by category",
            input_schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                },
            },
            handler=list_templates,
            mutates=False,
        ),
    ]
