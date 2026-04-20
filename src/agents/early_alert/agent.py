"""Early Alert sub-agent — detects at-risk students and recommends interventions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

# MCP tools this agent is allowed to use (from manifest).
ALLOWED_TOOLS = [
    "analytics.query",
    "roster.get",
    "interventions.playbook",
    "graph.evidence_summary",
]


class EarlyAlertAgent(BaseAgent):
    """Detects at-risk students with explanations and recommends interventions."""

    name = "early_alert"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        scope: dict = inputs["scope"]
        window_days: int = inputs.get("window_days", 14)
        risk_threshold: float = inputs.get("risk_threshold", 0.5)

        # Step 1: Get roster for the requested scope
        roster = await tools.call("roster.get", **scope)
        students = roster.get("students", [])

        if not students:
            return {
                "at_risk": [],
                "methodology_note": (
                    "No students found in the requested scope. "
                    "Verify the scope parameters and try again."
                ),
            }

        # Step 2: Query engagement and performance analytics
        analytics = await tools.call(
            "analytics.query",
            scope=scope,
            window_days=window_days,
            metrics=["login_frequency", "assignment_completion", "grade_trend"],
        )
        analytics_by_student: dict[str, dict] = {
            entry["student_id"]: entry
            for entry in analytics.get("rows", [])
        }

        # Step 3: Get learning-graph evidence summaries
        student_ids = [s["student_id"] for s in students]
        graph_evidence = await tools.call(
            "graph.evidence_summary",
            student_ids=student_ids,
            **scope,
        )
        evidence_by_student: dict[str, dict] = {
            entry["student_id"]: entry
            for entry in graph_evidence.get("summaries", [])
        }

        # Step 4: Compute risk for each student
        at_risk: list[dict] = []
        for student in students:
            sid = student["student_id"]
            name = student.get("display_name", sid)

            student_analytics = analytics_by_student.get(sid, {})
            student_evidence = evidence_by_student.get(sid, {})

            risk_score, confidence, factors = self._compute_risk(
                student_analytics, student_evidence, window_days
            )

            if risk_score >= risk_threshold:
                at_risk.append({
                    "student_id": sid,
                    "name": wrap_user_content(name),
                    "risk_score": round(risk_score, 2),
                    "confidence": round(confidence, 2),
                    "factors": factors,
                    "recommended_interventions": [],  # filled in next step
                })

        # Step 5: Look up interventions for flagged students
        if at_risk:
            all_factor_categories = set()
            for entry in at_risk:
                for factor in entry["factors"]:
                    all_factor_categories.add(self._categorize_factor(factor))

            playbook = await tools.call(
                "interventions.playbook",
                categories=sorted(all_factor_categories),
            )
            interventions_map: dict[str, list[str]] = {
                item["category"]: item.get("strategies", [])
                for item in playbook.get("interventions", [])
            }

            for entry in at_risk:
                recommendations: list[str] = []
                seen: set[str] = set()
                for factor in entry["factors"]:
                    category = self._categorize_factor(factor)
                    for strategy in interventions_map.get(category, []):
                        if strategy not in seen:
                            recommendations.append(strategy)
                            seen.add(strategy)
                entry["recommended_interventions"] = recommendations

        # Sort by risk score descending
        at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

        # Step 6: Build methodology note
        n = len(students)
        methodology_note = self._build_methodology_note(
            n, window_days, risk_threshold
        )

        return {
            "at_risk": at_risk,
            "methodology_note": methodology_note,
        }

    def _compute_risk(
        self,
        analytics: dict,
        evidence: dict,
        window_days: int,
    ) -> tuple[float, float, list[str]]:
        """Compute a risk score from analytics and graph evidence.

        Returns (risk_score, confidence, factors).

        In production this would be replaced by a proper model call.
        This placeholder uses simple heuristics so the scaffold is testable.
        """
        factors: list[str] = []
        scores: list[float] = []
        data_points = 0

        # Engagement signal: login frequency relative to median
        login_ratio = analytics.get("login_ratio")
        if login_ratio is not None:
            data_points += 1
            if login_ratio < 0.5:
                engagement_risk = 0.9
                pct = int((1 - login_ratio) * 100)
                factors.append(
                    f"Login frequency dropped {pct}% compared to class median"
                )
            elif login_ratio < 0.75:
                engagement_risk = 0.6
                factors.append("Login frequency below class median")
            else:
                engagement_risk = 0.1
            scores.append(engagement_risk)

        # Assessment signal: assignment completion and grade trend
        completion_rate = analytics.get("assignment_completion_rate")
        if completion_rate is not None:
            data_points += 1
            missed = analytics.get("assignments_missed", 0)
            total = analytics.get("assignments_total", 0)
            if completion_rate < 0.5:
                assessment_risk = 0.9
                factors.append(
                    f"Missed {missed} of last {total} assignments"
                )
            elif completion_rate < 0.75:
                assessment_risk = 0.6
                factors.append(
                    f"Completed only {int(completion_rate * 100)}% of recent assignments"
                )
            else:
                assessment_risk = 0.1
            scores.append(assessment_risk)

        grade_trend = analytics.get("grade_trend")
        if grade_trend is not None:
            data_points += 1
            if grade_trend < -0.15:
                trend_risk = 0.8
                factors.append("Grade trend declining significantly")
            elif grade_trend < 0:
                trend_risk = 0.4
                factors.append("Grade trend slightly declining")
            else:
                trend_risk = 0.1
            scores.append(trend_risk)

        # Graph evidence signal: stalled nodes
        stalled_nodes = evidence.get("stalled_nodes", 0)
        if stalled_nodes > 0:
            data_points += 1
            graph_risk = min(1.0, stalled_nodes * 0.3)
            factors.append(
                f"Stalled on {stalled_nodes} prerequisite node(s) in learning graph"
            )
            scores.append(graph_risk)

        if not scores:
            return 0.0, 0.0, ["Insufficient data to compute risk"]

        risk_score = sum(scores) / len(scores)

        # Confidence scales with the number of data points available
        max_points = 4  # login, completion, grade_trend, graph
        confidence = min(1.0, data_points / max_points)

        return risk_score, confidence, factors

    def _categorize_factor(self, factor: str) -> str:
        """Map a factor description to a playbook category."""
        lower = factor.lower()
        if "login" in lower or "engagement" in lower:
            return "engagement"
        if "assignment" in lower or "missed" in lower or "completion" in lower:
            return "assignment_completion"
        if "grade" in lower or "trend" in lower:
            return "grade_decline"
        if "stalled" in lower or "graph" in lower or "prerequisite" in lower:
            return "mastery_gap"
        return "general"

    def _build_methodology_note(
        self, n: int, window_days: int, risk_threshold: float
    ) -> str:
        """Build a human-readable methodology note."""
        parts = [
            f"Risk computed from engagement analytics (login frequency), "
            f"assessment performance (completion rate, grade trend), "
            f"and learning-graph progress (stalled nodes) "
            f"over a {window_days}-day window.",
            f"N={n} student(s) in scope.",
            f"Scores at or above {risk_threshold} are flagged.",
        ]
        if n < 15:
            parts.append(
                f"With {n} student(s), individual variation has outsized "
                f"influence on relative rankings. Interpret scores as "
                f"directional indicators."
            )
        return " ".join(parts)
