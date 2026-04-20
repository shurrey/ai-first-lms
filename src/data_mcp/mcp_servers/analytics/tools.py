"""Analytics MCP server tool handlers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef

# ---------------------------------------------------------------------------
# Schema description (static)
# ---------------------------------------------------------------------------

_SCHEMA_DESCRIPTION = {
    "tables": [
        "nodes", "edges", "evidence", "attestations", "persons",
        "enrollments", "sessions", "turns", "events_log",
    ],
    "events": [
        "attempt", "completion", "mastery_check", "artifact_submission",
        "dialogue_turn", "engagement_event",
    ],
    "metrics": [
        "evidence_count", "avg_score", "mastery_rate", "engagement_count",
    ],
    "dimensions": [
        "course_id", "person_id", "node_id", "kind", "observed_at",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _window_conditions(
    window: dict[str, str],
    col: str,
    params: list[Any],
    idx: int,
) -> tuple[list[str], int]:
    """Return (conditions, next_idx) for a time-window filter."""
    conditions: list[str] = []
    start = window.get("start")
    end = window.get("end")
    if start:
        conditions.append(f"{col} >= ${idx}::timestamptz")
        params.append(_parse_ts(start))
        idx += 1
    if end:
        conditions.append(f"{col} <= ${idx}::timestamptz")
        params.append(_parse_ts(end))
        idx += 1
    return conditions, idx


def _scope_conditions(
    scope: dict[str, Any],
    table_alias: str,
    params: list[Any],
    idx: int,
) -> tuple[list[str], int]:
    """Return (conditions, next_idx) for a scope filter (course_id / person_id)."""
    conditions: list[str] = []
    if "course_id" in scope:
        conditions.append(
            f"{table_alias}.node_id IN "
            f"(SELECT id FROM nodes WHERE metadata->>'course_id' = ${idx})"
        )
        params.append(str(scope["course_id"]))
        idx += 1
    if "person_id" in scope:
        conditions.append(f"{table_alias}.person_id = ${idx}::uuid")
        params.append(str(scope["person_id"]))
        idx += 1
    return conditions, idx


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all analytics server tool definitions."""

    async def query(args: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = args.get("scope", {})
        metric: str = args.get("metric", "evidence_count")
        window: dict[str, str] = args.get("window", {})
        breakdown: str | None = args.get("breakdown")
        filters: dict[str, Any] = args.get("filters") or {}

        async with pool.acquire() as conn:
            params: list[Any] = []
            idx = 1
            conditions: list[str] = []

            scope_conds, idx = _scope_conditions(scope, "e", params, idx)
            conditions.extend(scope_conds)

            win_conds, idx = _window_conditions(window, "e.observed_at", params, idx)
            conditions.extend(win_conds)

            # Extra filters (kind, node_id)
            if "kind" in filters:
                conditions.append(f"e.kind = ${idx}")
                params.append(filters["kind"])
                idx += 1
            if "node_id" in filters:
                conditions.append(f"e.node_id = ${idx}::uuid")
                params.append(str(filters["node_id"]))
                idx += 1

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            if metric == "evidence_count":
                agg = "COUNT(*)"
            elif metric == "avg_score":
                conditions_inner = conditions + ["e.score IS NOT NULL"]
                where = f"WHERE {' AND '.join(conditions_inner)}" if conditions_inner else ""
                agg = "AVG(e.score)"
            elif metric == "engagement_count":
                conditions_inner = conditions + ["e.kind = 'engagement_event'"]
                where = f"WHERE {' AND '.join(conditions_inner)}" if conditions_inner else ""
                agg = "COUNT(*)"
            elif metric == "mastery_rate":
                agg = (
                    "CASE WHEN COUNT(*) = 0 THEN 0 "
                    "ELSE COUNT(*) FILTER (WHERE a.level = 'mastery')::float / COUNT(*) END"
                )
            else:
                return {"rows": [], "metadata": {"error": f"Unknown metric: {metric}"}}

            if metric == "mastery_rate":
                # Use attestations table
                att_conditions: list[str] = []
                att_params: list[Any] = []
                att_idx = 1
                att_scope_conds, att_idx = _scope_conditions(scope, "a", att_params, att_idx)
                att_conditions.extend(att_scope_conds)
                att_where = f"WHERE {' AND '.join(att_conditions)}" if att_conditions else ""

                group_clause = ""
                select_extra = ""
                if breakdown:
                    select_extra = f", a.{breakdown} AS dimension"
                    group_clause = f"GROUP BY a.{breakdown}"

                sql = (
                    f"SELECT {agg} AS value, COUNT(DISTINCT person_id) AS sample_size"
                    f"{select_extra} FROM attestations a {att_where} {group_clause}"
                )
                rows = await conn.fetch(sql, *att_params)
            else:
                group_clause = ""
                select_extra = ""
                if breakdown:
                    select_extra = f", e.{breakdown} AS dimension"
                    group_clause = f"GROUP BY e.{breakdown}"

                sql = (
                    f"SELECT {agg} AS value, COUNT(DISTINCT person_id) AS sample_size"
                    f"{select_extra} FROM evidence e {where} {group_clause}"
                )
                rows = await conn.fetch(sql, *params)

            result_rows = []
            for r in rows:
                row: dict[str, Any] = {
                    "value": float(r["value"]) if r["value"] is not None else 0.0,
                    "sample_size": int(r["sample_size"]) if r["sample_size"] is not None else 0,
                }
                if breakdown and "dimension" in r.keys():
                    row["dimension"] = str(r["dimension"]) if r["dimension"] is not None else None
                result_rows.append(row)

            return {
                "rows": result_rows,
                "metadata": {"metric": metric, "scope": scope, "window": window},
            }

    async def describe_schema(args: dict[str, Any]) -> dict[str, Any]:
        return _SCHEMA_DESCRIPTION

    async def trend(args: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = args.get("scope", {})
        metric: str = args.get("metric", "evidence_count")
        window: dict[str, str] = args.get("window", {})
        interval: str = args.get("interval", "day")

        # Map interval to Postgres date_trunc argument
        trunc_map = {
            "hour": "hour",
            "day": "day",
            "week": "week",
            "month": "month",
        }
        trunc = trunc_map.get(interval, "day")

        async with pool.acquire() as conn:
            params: list[Any] = []
            idx = 1
            conditions: list[str] = []

            scope_conds, idx = _scope_conditions(scope, "e", params, idx)
            conditions.extend(scope_conds)

            win_conds, idx = _window_conditions(window, "e.observed_at", params, idx)
            conditions.extend(win_conds)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            if metric == "avg_score":
                conditions = conditions + ["e.score IS NOT NULL"]
                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                agg = "AVG(e.score)"
            elif metric == "engagement_count":
                conditions = conditions + ["e.kind = 'engagement_event'"]
                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                agg = "COUNT(*)"
            elif metric == "mastery_rate":
                # Mastery rate trend not supported via evidence; fall back to count
                agg = "COUNT(*)"
            else:
                agg = "COUNT(*)"

            sql = (
                f"SELECT date_trunc('{trunc}', e.observed_at) AS bucket, "
                f"{agg} AS y "
                f"FROM evidence e {where} "
                f"GROUP BY bucket ORDER BY bucket"
            )
            rows = await conn.fetch(sql, *params)

            series = []
            for r in rows:
                bucket = r["bucket"]
                x = bucket.isoformat() if bucket else None
                series.append({"x": x, "y": float(r["y"]) if r["y"] is not None else 0.0})

            return {"series": series}

    async def cohort_compare(args: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = args.get("scope", {})
        cohorts: list[dict[str, Any]] = args.get("cohorts", [])
        metric: str = args.get("metric", "evidence_count")
        window: dict[str, str] = args.get("window", {})

        async with pool.acquire() as conn:
            cohort_results = []

            for cohort in cohorts:
                cohort_scope = {**scope, **cohort.get("scope", {})}
                params: list[Any] = []
                idx = 1
                conditions: list[str] = []

                scope_conds, idx = _scope_conditions(cohort_scope, "e", params, idx)
                conditions.extend(scope_conds)

                win_conds, idx = _window_conditions(window, "e.observed_at", params, idx)
                conditions.extend(win_conds)

                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                if metric == "avg_score":
                    conditions = conditions + ["e.score IS NOT NULL"]
                    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                    agg = "AVG(e.score)"
                elif metric == "engagement_count":
                    conditions = conditions + ["e.kind = 'engagement_event'"]
                    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                    agg = "COUNT(*)"
                else:
                    agg = "COUNT(*)"

                sql = (
                    f"SELECT {agg} AS value, COUNT(DISTINCT person_id) AS sample_size "
                    f"FROM evidence e {where}"
                )
                row = await conn.fetchrow(sql, *params)
                cohort_results.append({
                    "cohort": cohort.get("label", str(cohort)),
                    "value": float(row["value"]) if row and row["value"] is not None else 0.0,
                    "sample_size": int(row["sample_size"]) if row and row["sample_size"] is not None else 0,
                })

            return {"cohort_results": cohort_results}

    async def render_chart(args: dict[str, Any]) -> dict[str, Any]:
        series = args.get("series", [])
        chart_type = args.get("type", "line")
        title = args.get("title", "")

        # Build a Recharts-compatible chart spec
        chart_spec: dict[str, Any] = {
            "type": chart_type,
            "title": title,
            "data": series,
        }

        if chart_type in ("line", "scatter"):
            chart_spec["xKey"] = "x"
            chart_spec["yKey"] = "y"
            chart_spec["xAxis"] = {"label": "x"}
            chart_spec["yAxis"] = {"label": "y"}
        elif chart_type == "bar":
            chart_spec["xKey"] = "x"
            chart_spec["yKey"] = "y"
            chart_spec["xAxis"] = {"label": "x"}
            chart_spec["yAxis"] = {"label": "y"}
        elif chart_type == "histogram":
            chart_spec["dataKey"] = "y"
            chart_spec["bins"] = 10

        return {"chart_spec": chart_spec}

    return [
        ToolDef(
            name="analytics.query",
            description="Run an analytics query over the learning graph",
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {"type": "object"},
                    "metric": {"type": "string"},
                    "window": {"type": "object"},
                    "breakdown": {"type": "string"},
                    "filters": {"type": "object"},
                },
                "required": ["scope", "metric", "window"],
            },
            handler=query,
        ),
        ToolDef(
            name="analytics.describe_schema",
            description="Return the analytics schema description",
            input_schema={"type": "object", "properties": {}},
            handler=describe_schema,
        ),
        ToolDef(
            name="analytics.trend",
            description="Return a time-series trend for a metric",
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {"type": "object"},
                    "metric": {"type": "string"},
                    "window": {"type": "object"},
                    "interval": {"type": "string"},
                },
                "required": ["scope", "metric", "window", "interval"],
            },
            handler=trend,
        ),
        ToolDef(
            name="analytics.cohort_compare",
            description="Compare a metric across multiple cohorts",
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {"type": "object"},
                    "cohorts": {"type": "array", "items": {"type": "object"}},
                    "metric": {"type": "string"},
                    "window": {"type": "object"},
                },
                "required": ["scope", "cohorts", "metric", "window"],
            },
            handler=cohort_compare,
        ),
        ToolDef(
            name="analytics.render_chart",
            description="Render a Recharts-compatible chart spec from series data",
            input_schema={
                "type": "object",
                "properties": {
                    "series": {"type": "array"},
                    "type": {"type": "string", "enum": ["line", "bar", "scatter", "histogram"]},
                    "title": {"type": "string"},
                },
                "required": ["series", "type", "title"],
            },
            handler=render_chart,
        ),
    ]
