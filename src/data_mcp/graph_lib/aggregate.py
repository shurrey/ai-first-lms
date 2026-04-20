"""Aggregate analytics over the learning graph."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg


def _parse_ts(s: str | None) -> datetime | None:
    """Parse an ISO timestamp string to a datetime."""
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def aggregate(
    pool: asyncpg.Pool,
    scope: dict[str, Any],
    metric: str,
    window: dict[str, str],
) -> dict[str, Any]:
    """Compute aggregate metrics over graph data.

    Args:
        pool: asyncpg connection pool
        scope: filter scope, e.g. {"course_id": "..."} or {"person_id": "..."}
        metric: one of "evidence_count", "avg_score", "mastery_rate", "engagement_count"
        window: {"start": ISO timestamp, "end": ISO timestamp}

    Returns:
        {"value": number, "sample_size": int, "caveats": []}
    """
    async with pool.acquire() as conn:
        start = window.get("start")
        end = window.get("end")
        caveats: list[str] = []

        if metric == "evidence_count":
            query, params = _build_evidence_count_query(scope, start, end)
        elif metric == "avg_score":
            query, params = _build_avg_score_query(scope, start, end)
        elif metric == "mastery_rate":
            query, params = _build_mastery_rate_query(scope)
        elif metric == "engagement_count":
            query, params = _build_engagement_count_query(scope, start, end)
        else:
            return {"value": 0, "sample_size": 0, "caveats": [f"Unknown metric: {metric}"]}

        row = await conn.fetchrow(query, *params)
        value = float(row["value"]) if row and row["value"] is not None else 0.0
        sample_size = int(row["sample_size"]) if row and row["sample_size"] is not None else 0

        if sample_size < 5:
            caveats.append(f"Small sample size ({sample_size}); interpret with caution.")

        return {"value": value, "sample_size": sample_size, "caveats": caveats}


def _build_evidence_count_query(
    scope: dict[str, Any], start: str | None, end: str | None
) -> tuple[str, list[Any]]:
    conditions = []
    params: list[Any] = []
    idx = 1

    if "course_id" in scope:
        conditions.append(f"e.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = ${idx})")
        params.append(str(scope["course_id"]))
        idx += 1
    if "person_id" in scope:
        conditions.append(f"e.person_id = ${idx}::uuid")
        params.append(str(scope["person_id"]))
        idx += 1
    if start:
        conditions.append(f"e.observed_at >= ${idx}::timestamptz")
        params.append(_parse_ts(start))
        idx += 1
    if end:
        conditions.append(f"e.observed_at <= ${idx}::timestamptz")
        params.append(_parse_ts(end))
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return (
        f"SELECT COUNT(*) AS value, COUNT(DISTINCT person_id) AS sample_size FROM evidence e {where}",
        params,
    )


def _build_avg_score_query(
    scope: dict[str, Any], start: str | None, end: str | None
) -> tuple[str, list[Any]]:
    conditions = ["e.score IS NOT NULL"]
    params: list[Any] = []
    idx = 1

    if "course_id" in scope:
        conditions.append(f"e.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = ${idx})")
        params.append(str(scope["course_id"]))
        idx += 1
    if "person_id" in scope:
        conditions.append(f"e.person_id = ${idx}::uuid")
        params.append(str(scope["person_id"]))
        idx += 1
    if start:
        conditions.append(f"e.observed_at >= ${idx}::timestamptz")
        params.append(_parse_ts(start))
        idx += 1
    if end:
        conditions.append(f"e.observed_at <= ${idx}::timestamptz")
        params.append(_parse_ts(end))
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}"
    return (
        f"SELECT AVG(e.score) AS value, COUNT(*) AS sample_size FROM evidence e {where}",
        params,
    )


def _build_mastery_rate_query(scope: dict[str, Any]) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if "course_id" in scope:
        conditions.append(
            f"a.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = ${idx})"
        )
        params.append(str(scope["course_id"]))
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return (
        f"""SELECT
              CASE WHEN COUNT(*) = 0 THEN 0
                   ELSE COUNT(*) FILTER (WHERE a.level = 'mastery')::float / COUNT(*)
              END AS value,
              COUNT(DISTINCT person_id) AS sample_size
            FROM attestations a {where}""",
        params,
    )


def _build_engagement_count_query(
    scope: dict[str, Any], start: str | None, end: str | None
) -> tuple[str, list[Any]]:
    conditions = ["e.kind = 'engagement_event'"]
    params: list[Any] = []
    idx = 1

    if "course_id" in scope:
        conditions.append(f"e.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = ${idx})")
        params.append(str(scope["course_id"]))
        idx += 1
    if start:
        conditions.append(f"e.observed_at >= ${idx}::timestamptz")
        params.append(_parse_ts(start))
        idx += 1
    if end:
        conditions.append(f"e.observed_at <= ${idx}::timestamptz")
        params.append(_parse_ts(end))
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}"
    return (
        f"SELECT COUNT(*) AS value, COUNT(DISTINCT person_id) AS sample_size FROM evidence e {where}",
        params,
    )
