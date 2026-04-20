"""Engagement Analyst sub-agent — NL questions over learning analytics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

ALLOWED_TOOLS = [
    "analytics.query",
    "analytics.describe_schema",
    "charts.render",
    "graph.aggregate",
]


class EngagementAnalystAgent(BaseAgent):
    """Answers NL questions over learning analytics with charts and narratives."""

    name = "engagement_analyst"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        question: str = inputs["question"]
        scope: dict[str, Any] = inputs.get("scope", {})
        window: dict[str, Any] = inputs.get("window", {})

        # Step 1: Understand the schema
        schema = await tools.call("analytics.describe_schema")

        # Step 2: Query the data
        query_result = await tools.call(
            "analytics.query",
            scope=scope,
            metric=question,
            window=window,
        )
        rows = query_result.get("rows", [])

        # Step 3: Build caveats
        caveats: list[str] = []
        sample_size = len(rows)
        if sample_size < 30:
            caveats.append(
                f"Sample size is {sample_size} — interpret with caution."
            )

        # Step 4: Render chart if data available
        charts: list[dict[str, Any]] = []
        if rows:
            chart_type = self._select_chart_type(question)
            chart_spec = await tools.call(
                "charts.render",
                series=rows,
                type=chart_type,
                title=question,
            )
            charts.append({
                "type": chart_type,
                "title": question,
                "data_ref": chart_spec.get("chart_spec", {}),
            })

        # Step 5: Build narrative
        narrative = self._build_narrative(question, rows, caveats)

        return {
            "narrative_md": narrative,
            "charts": charts,
            "caveats": caveats,
            "query_used": str(query_result.get("metadata", {}).get("query", "")),
        }

    def _select_chart_type(self, question: str) -> str:
        q = question.lower()
        if any(w in q for w in ["trend", "over time", "daily", "weekly", "monthly"]):
            return "line"
        if any(w in q for w in ["compare", "comparison", "vs", "versus"]):
            return "bar"
        if any(w in q for w in ["distribution", "spread"]):
            return "histogram"
        return "bar"

    def _build_narrative(
        self, question: str, rows: list[Any], caveats: list[str]
    ) -> str:
        if not rows:
            return f"No data found for the query: '{question}'."
        caveat_text = " ".join(caveats) if caveats else ""
        return (
            f"Based on the available data for '{question}', "
            f"there are {len(rows)} data points. {caveat_text}"
        )
