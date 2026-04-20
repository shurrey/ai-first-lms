"""Advising sub-agent — academic planning, degree audit, and pathway mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

# MCP tools this agent is allowed to use (from manifest).
ALLOWED_TOOLS = [
    "sis.get_transcript",
    "sis.degree_audit",
    "sis.check_prerequisites",
    "catalog.search",
    "schedule.availability",
    "graph.path_to_mastery",
]


class AdvisingAgent(BaseAgent):
    """Academic advising agent for students and advisors."""

    name = "advising"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        student_id: str = inputs["student_id"]
        intent: str = inputs["intent"]
        constraints: dict[str, Any] = inputs.get("constraints") or {}

        # Step 1: Always start with a degree audit and transcript
        audit_raw = await tools.call(
            "sis.degree_audit", student_id=student_id
        )
        transcript_raw = await tools.call(
            "sis.get_transcript", student_id=student_id
        )

        # Wrap retrieved data for safety
        audit = self._wrap_audit(audit_raw)
        transcript = wrap_user_content(str(transcript_raw))

        # Step 2: Dispatch based on intent
        if intent == "next_term":
            return await self._handle_next_term(
                student_id, audit_raw, constraints, tools
            )
        elif intent == "degree_plan":
            return await self._handle_degree_plan(
                student_id, audit_raw, constraints, tools
            )
        elif intent == "pathway_explore":
            return await self._handle_pathway_explore(
                student_id, audit_raw, constraints, tools
            )
        elif intent == "learning_path":
            return await self._handle_learning_path(
                student_id, audit_raw, constraints, tools
            )
        else:
            raise ValueError(f"Unknown intent: {intent}")

    async def _handle_next_term(
        self,
        student_id: str,
        audit: dict[str, Any],
        constraints: dict[str, Any],
        tools: ToolBag,
    ) -> dict[str, Any]:
        """Recommend courses for the next term."""
        remaining = audit.get("remaining", [])
        recommendations: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        max_credits = constraints.get("max_credits", 15)

        # Check prerequisites and availability for remaining courses
        credit_total = 0
        for req in remaining:
            course_id = req.get("course_id", "")
            credits = req.get("credits", 3)

            if credit_total + credits > max_credits:
                continue

            prereq_result = await tools.call(
                "sis.check_prerequisites",
                student_id=student_id,
                course_id=course_id,
            )
            prereqs_met = prereq_result.get("met", False)

            availability = await tools.call(
                "schedule.availability",
                course_id=course_id,
                term="next",
            )
            is_available = availability.get("available", False)

            if prereqs_met and is_available:
                recommendations.append({
                    "course_id": course_id,
                    "title": req.get("title", course_id),
                    "rationale": f"Required for degree; prerequisites met.",
                    "prerequisites_met": True,
                    "priority": req.get("priority", "required"),
                })
                credit_total += credits
            elif not prereqs_met:
                risks.append({
                    "type": "missing_prerequisite",
                    "description": (
                        f"Cannot take {course_id}: missing prerequisites "
                        f"{prereq_result.get('missing', [])}"
                    ),
                    "mitigation": "Complete missing prerequisites first.",
                })

        return {
            "audit": audit,
            "recommendations": recommendations,
            "alternatives": [],
            "risks": risks,
        }

    async def _handle_degree_plan(
        self,
        student_id: str,
        audit: dict[str, Any],
        constraints: dict[str, Any],
        tools: ToolBag,
    ) -> dict[str, Any]:
        """Full degree plan with time-to-graduation projection."""
        remaining = audit.get("remaining", [])
        recommendations: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []

        for req in remaining:
            course_id = req.get("course_id", "")
            prereq_result = await tools.call(
                "sis.check_prerequisites",
                student_id=student_id,
                course_id=course_id,
            )
            recommendations.append({
                "course_id": course_id,
                "title": req.get("title", course_id),
                "rationale": "Remaining degree requirement.",
                "prerequisites_met": prereq_result.get("met", False),
                "priority": req.get("priority", "required"),
            })

            if not prereq_result.get("met", False):
                risks.append({
                    "type": "missing_prerequisite",
                    "description": (
                        f"{course_id} has unmet prerequisites: "
                        f"{prereq_result.get('missing', [])}"
                    ),
                    "mitigation": "Schedule prerequisite courses in an earlier term.",
                })

        # Estimate time to graduation
        total_remaining_credits = sum(r.get("credits", 3) for r in remaining)
        credits_per_term = constraints.get("max_credits", 15)
        terms_remaining = (
            (total_remaining_credits + credits_per_term - 1) // credits_per_term
            if credits_per_term > 0
            else 0
        )

        if terms_remaining > 4:
            risks.append({
                "type": "graduation_delay",
                "description": (
                    f"At {credits_per_term} credits/term, graduation is "
                    f"~{terms_remaining} terms away."
                ),
                "mitigation": "Consider increasing course load or summer sessions.",
            })

        return {
            "audit": audit,
            "recommendations": recommendations,
            "alternatives": [],
            "risks": risks,
        }

    async def _handle_pathway_explore(
        self,
        student_id: str,
        audit: dict[str, Any],
        constraints: dict[str, Any],
        tools: ToolBag,
    ) -> dict[str, Any]:
        """Explore alternative academic pathways (e.g., adding a minor)."""
        target = constraints.get("target", "")

        # Search catalog for the target pathway
        catalog_results = await tools.call(
            "catalog.search", query=target
        )

        alternatives: list[dict[str, Any]] = []
        for option in catalog_results.get("results", []):
            alternatives.append({
                "scenario": f"Add {option.get('title', target)}",
                "courses": option.get("required_courses", []),
                "trade_offs": (
                    f"Adds {option.get('additional_credits', '?')} credits "
                    f"to your plan."
                ),
                "time_to_graduation_delta": option.get("time_delta", "unknown"),
            })

        return {
            "audit": audit,
            "recommendations": [],
            "alternatives": alternatives,
            "risks": [],
        }

    async def _handle_learning_path(
        self,
        student_id: str,
        audit: dict[str, Any],
        constraints: dict[str, Any],
        tools: ToolBag,
    ) -> dict[str, Any]:
        """Navigate learning graph to a target competency."""
        target_node = constraints.get("target_node", "")

        path_result = await tools.call(
            "graph.path_to_mastery",
            student_id=student_id,
            target_node=target_node,
        )

        recommendations: list[dict[str, Any]] = []
        for step in path_result.get("path", []):
            recommendations.append({
                "course_id": step.get("node_id", ""),
                "title": step.get("title", step.get("node_id", "")),
                "rationale": (
                    f"Mastery level: {step.get('mastery_level', 'unknown')} "
                    f"(confidence: {step.get('confidence', 0)})"
                ),
                "prerequisites_met": True,
                "priority": "recommended",
            })

        return {
            "audit": audit,
            "recommendations": recommendations,
            "alternatives": [],
            "risks": [],
            "path_visualization": path_result,
        }

    def _wrap_audit(self, audit: dict[str, Any]) -> dict[str, Any]:
        """Wrap string fields in the audit for prompt-injection safety."""
        wrapped = dict(audit)
        for key in ("completed", "in_progress", "remaining"):
            items = wrapped.get(key, [])
            if isinstance(items, list):
                wrapped[key] = [
                    {
                        **item,
                        "title": wrap_user_content(item["title"])
                        if isinstance(item.get("title"), str)
                        else item.get("title", ""),
                    }
                    for item in items
                    if isinstance(item, dict)
                ]
        return wrapped
