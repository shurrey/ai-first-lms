"""Shared helpers for MCP server tool handlers."""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg


async def resolve_concept_id(
    conn: asyncpg.Connection, value: str,
) -> uuid.UUID | None:
    """Resolve a concept identifier that may be a UUID or a title.

    Returns the UUID if valid, or looks up the concept by title.
    Returns None if the concept is not found by title.
    """
    try:
        return uuid.UUID(value)
    except ValueError:
        row = await conn.fetchrow(
            "SELECT id FROM nodes WHERE LOWER(title) = LOWER($1) AND kind = 'concept'",
            value,
        )
        return row["id"] if row else None


def parse_json_column(value: Any) -> dict[str, Any]:
    """Parse a JSON/JSONB column value that may be a dict, a JSON string, or None.

    asyncpg returns JSONB columns as dicts, but plain TEXT/VARCHAR columns
    storing JSON come back as strings. This normalises both cases.
    """
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value
