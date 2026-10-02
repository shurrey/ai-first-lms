"""Analytics MCP server tool handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from data_mcp.mcp_base import ToolDef
from data_mcp.mcp_servers._helpers import validation_error

# ---------------------------------------------------------------------------
# Schema description (static)
# ---------------------------------------------------------------------------

# Dimensions analytics.query may break down by, per source table. Column names
# cannot be bound as parameters, so each one is a CASE branch in the static SQL
# below and this whitelist is checked before any query runs.
EVIDENCE_DIMENSIONS = frozenset({"kind", "node_id", "person_id", "source", "observed_at"})
ATTESTATION_DIMENSIONS = frozenset({"level", "node_id", "person_id", "issuer_id"})

# Mirrors the evidence_kind enum in contracts/db-schema.sql.
EVIDENCE_KINDS = (
    "attempt", "completion", "mastery_check", "artifact_submission",
    "dialogue_turn", "engagement_event",
)

_SCHEMA_DESCRIPTION = {
    "tables": [
        "nodes", "edges", "evidence", "attestations", "persons",
        "enrollments", "sessions", "turns", "events_log",
    ],
    "events": list(EVIDENCE_KINDS),
    "metrics": [
        "evidence_count", "avg_score", "mastery_rate", "engagement_count",
    ],
    "dimensions": sorted(EVIDENCE_DIMENSIONS | ATTESTATION_DIMENSIONS),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVIDENCE_METRICS = frozenset({"evidence_count", "avg_score", "engagement_count"})
_TREND_INTERVALS = frozenset({"hour", "day", "week", "month"})

# One statement serves query, trend and cohort_compare. A NULL dimension ($8)
# or bucket field ($9) collapses that grouping column to a single NULL group.
_EVIDENCE_AGG_SQL = """
SELECT
    CASE $8::text
        WHEN 'kind'      THEN e.kind::text
        WHEN 'node_id'   THEN e.node_id::text
        WHEN 'person_id' THEN e.person_id::text
        WHEN 'source'    THEN e.source
        WHEN 'observed_at' THEN e.observed_at::text
    END AS dimension,
    date_trunc($9::text, e.observed_at) AS bucket,
    CASE WHEN $7::text = 'avg_score' THEN AVG(e.score) ELSE COUNT(*) END AS value,
    COUNT(DISTINCT e.person_id) AS sample_size
FROM evidence e
WHERE ($1::text IS NULL
       OR e.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = $1))
  AND ($2::uuid IS NULL OR e.person_id = $2)
  AND ($3::timestamptz IS NULL OR e.observed_at >= $3)
  AND ($4::timestamptz IS NULL OR e.observed_at <= $4)
  AND ($5::text IS NULL OR e.kind = $5::text::evidence_kind)
  AND ($6::uuid IS NULL OR e.node_id = $6)
  AND ($7::text <> 'avg_score' OR e.score IS NOT NULL)
  AND ($7::text <> 'engagement_count' OR e.kind = 'engagement_event')
GROUP BY 1, 2
ORDER BY 2
"""

_MASTERY_RATE_SQL = """
SELECT
    CASE $3::text
        WHEN 'level'     THEN a.level::text
        WHEN 'node_id'   THEN a.node_id::text
        WHEN 'person_id' THEN a.person_id::text
        WHEN 'issuer_id' THEN a.issuer_id::text
    END AS dimension,
    CASE WHEN COUNT(*) = 0 THEN 0
         ELSE COUNT(*) FILTER (WHERE a.level = 'mastery')::float / COUNT(*) END AS value,
    COUNT(DISTINCT a.person_id) AS sample_size
FROM attestations a
WHERE ($1::text IS NULL
       OR a.node_id IN (SELECT id FROM nodes WHERE metadata->>'course_id' = $1))
  AND ($2::uuid IS NULL OR a.person_id = $2)
GROUP BY 1
"""


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _scope_params(scope: dict[str, Any]) -> list[Any]:
    """Bind values for the (course_id, person_id) scope filter; None means unfiltered."""
    course_id = scope.get("course_id")
    person_id = scope.get("person_id")
    return [
        str(course_id) if course_id is not None else None,
        str(person_id) if person_id is not None else None,
    ]


def _evidence_params(
    scope: dict[str, Any],
    window: dict[str, str],
    metric: str,
    filters: dict[str, Any] | None = None,
    dimension: str | None = None,
    bucket: str | None = None,
) -> list[Any]:
    """Bind values $1..$9 for _EVIDENCE_AGG_SQL, in placeholder order."""
    filters = filters or {}
    return [
        *_scope_params(scope),
        _parse_ts(window.get("start")),
        _parse_ts(window.get("end")),
        filters.get("kind"),
        str(filters["node_id"]) if filters.get("node_id") is not None else None,
        metric,
        dimension,
        bucket,
    ]


def _check_breakdown(breakdown: Any, allowed: frozenset[str]) -> str | None:
    """Return an error message if breakdown is not an allowed dimension, else None."""
    if breakdown is None or (isinstance(breakdown, str) and breakdown in allowed):
        return None
    return f"Invalid breakdown {breakdown!r}; allowed: {sorted(allowed)}"


def _check_filters(filters: Any) -> str | None:
    """Return an error message if filters is malformed or filters.kind is not an evidence kind."""
    if not isinstance(filters, dict):
        return f"Invalid filters {filters!r}; expected an object"
    kind = filters.get("kind")
    if kind is not None and not (isinstance(kind, str) and kind in EVIDENCE_KINDS):
        return f"Invalid filters.kind {kind!r}; allowed: {sorted(EVIDENCE_KINDS)}"
    return None


def _check_shape(scope: Any, window: Any, metric: Any, filters: Any = None) -> str | None:
    """Return an error message for arguments asyncpg would reject or that would raise, else None."""
    if not isinstance(scope, dict):
        return f"Invalid scope {scope!r}; expected an object"
    if not isinstance(window, dict):
        return f"Invalid window {window!r}; expected an object"
    if not isinstance(metric, str):
        return f"Invalid metric {metric!r}; expected a string"
    uuids = {"scope.person_id": scope.get("person_id")}
    if isinstance(filters, dict):
        uuids["filters.node_id"] = filters.get("node_id")
    for name, value in uuids.items():
        if value is None:
            continue
        try:
            UUID(str(value))
        except ValueError:
            return f"Invalid {name} {value!r}; expected a UUID"
    for bound in ("start", "end"):
        value = window.get(bound)
        try:
            _parse_ts(value)
        except (TypeError, ValueError, AttributeError):
            return f"Invalid window.{bound} {value!r}; expected an ISO-8601 timestamp"
    return None


def _to_float(value: Any) -> float:
    return float(value) if value is not None else 0.0


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all analytics server tool definitions."""

    async def query(args: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = args.get("scope", {})
        metric: str = args.get("metric", "evidence_count")
        window: dict[str, str] = args.get("window", {})
        breakdown: str | None = args.get("breakdown") or None
        filters: dict[str, Any] = args.get("filters") or {}

        shape_error = _check_shape(scope, window, metric, filters)
        if shape_error:
            return {
                **validation_error(shape_error),
                "rows": [],
                "metadata": {"error": shape_error},
            }
        if metric == "mastery_rate":
            error = _check_breakdown(breakdown, ATTESTATION_DIMENSIONS)
        elif metric in _EVIDENCE_METRICS:
            error = _check_breakdown(breakdown, EVIDENCE_DIMENSIONS)
        else:
            return {"rows": [], "metadata": {"error": f"Unknown metric: {metric}"}}
        error = error or _check_filters(filters)
        if error:
            return {
                **validation_error(error),
                "rows": [],
                "metadata": {"error": error, "metric": metric},
            }

        async with pool.acquire() as conn:
            if metric == "mastery_rate":
                rows = await conn.fetch(_MASTERY_RATE_SQL, *_scope_params(scope), breakdown)
            else:
                rows = await conn.fetch(
                    _EVIDENCE_AGG_SQL,
                    *_evidence_params(scope, window, metric, filters, dimension=breakdown),
                )

        result_rows = []
        for r in rows:
            row: dict[str, Any] = {
                "value": _to_float(r["value"]),
                "sample_size": int(r["sample_size"]) if r["sample_size"] is not None else 0,
            }
            if breakdown:
                row["dimension"] = r["dimension"]
            result_rows.append(row)
        # An ungrouped aggregate over zero rows still reports one zero-valued row.
        if not breakdown and not result_rows:
            result_rows.append({"value": 0.0, "sample_size": 0})

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
        interval = args.get("interval", "day")
        shape_error = _check_shape(scope, window, metric)
        if shape_error:
            return {**validation_error(shape_error), "series": []}
        trunc = interval if isinstance(interval, str) and interval in _TREND_INTERVALS else "day"
        # mastery_rate is attestation-based; its trend falls back to evidence count.
        evidence_metric = metric if metric in _EVIDENCE_METRICS else "evidence_count"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _EVIDENCE_AGG_SQL,
                *_evidence_params(scope, window, evidence_metric, bucket=trunc),
            )

        return {"series": [
            {"x": r["bucket"].isoformat() if r["bucket"] else None, "y": _to_float(r["value"])}
            for r in rows
        ]}

    async def cohort_compare(args: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = args.get("scope", {})
        cohorts: list[dict[str, Any]] = args.get("cohorts", [])
        metric: str = args.get("metric", "evidence_count")
        window: dict[str, str] = args.get("window", {})
        shape_error = _check_shape(scope, window, metric)
        if not shape_error and not isinstance(cohorts, list):
            shape_error = f"Invalid cohorts {cohorts!r}; expected an array"
        for cohort in cohorts if not shape_error else []:
            cohort_scope = cohort.get("scope", {}) if isinstance(cohort, dict) else None
            if not isinstance(cohort_scope, dict):
                shape_error = f"Invalid cohort {cohort!r}; expected an object with a scope object"
                break
            shape_error = _check_shape({**scope, **cohort_scope}, window, metric)
            if shape_error:
                break
        if shape_error:
            return {**validation_error(shape_error), "cohort_results": []}
        evidence_metric = metric if metric in _EVIDENCE_METRICS else "evidence_count"

        async with pool.acquire() as conn:
            cohort_results = []
            for cohort in cohorts:
                cohort_scope = {**scope, **cohort.get("scope", {})}
                row = await conn.fetchrow(
                    _EVIDENCE_AGG_SQL,
                    *_evidence_params(cohort_scope, window, evidence_metric),
                )
                cohort_results.append({
                    "cohort": cohort.get("label", str(cohort)),
                    "value": _to_float(row["value"]) if row else 0.0,
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
                    "breakdown": {
                        "type": "string",
                        "description": (
                            f"Evidence metrics: one of {sorted(EVIDENCE_DIMENSIONS)}; "
                            f"mastery_rate: one of {sorted(ATTESTATION_DIMENSIONS)}"
                        ),
                    },
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
