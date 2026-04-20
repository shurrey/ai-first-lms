"""Course Architect sub-agent — draft course structures and syllabi."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

ALLOWED_TOOLS = [
    "standards.lookup",
    "content.library_search",
    "graph.subgraph_for_outcomes",
    "content.save_draft",
]


class CourseArchitectAgent(BaseAgent):
    """Drafts course structures, outcomes, modules, and syllabi."""

    name = "course_architect"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        topic: str = inputs["topic"]
        audience: str = inputs["audience"]
        duration_weeks: int = inputs["duration_weeks"]
        standards_list: list[str] = inputs.get("standards", [])
        constraints: str | None = inputs.get("constraints")

        # Step 1: Look up standards if provided
        aligned_standards: list[dict[str, Any]] = []
        for framework in standards_list:
            result = await tools.call("standards.lookup", framework=framework)
            aligned_standards.extend(result.get("standards", []))

        # Step 2: Search existing content for reuse
        library_results = await tools.call(
            "content.library_search", query=topic, top_k=10
        )

        # Step 3: Draft outcomes with Bloom's levels
        outcomes = self._draft_outcomes(topic, audience, aligned_standards)

        # Step 4: Draft modules
        modules = self._draft_modules(topic, duration_weeks, outcomes)

        # Step 5: Build alignment matrix
        alignment = [
            {"outcome_id": f"outcome-{i+1}", "assessment_ids": []}
            for i in range(len(outcomes))
        ]

        # Step 6: Draft syllabus
        syllabus_md = self._draft_syllabus(
            topic, audience, duration_weeks, outcomes, modules, constraints
        )

        # Step 7: Save draft
        draft_result = await tools.call(
            "content.save_draft",
            kind="syllabus",
            title=f"Syllabus: {topic}",
            body_md=syllabus_md,
            author_id=persona.person_id,
        )

        return {
            "outcomes": outcomes,
            "modules": modules,
            "syllabus_md": syllabus_md,
            "alignment": alignment,
            "draft_id": draft_result.get("draft_id", ""),
        }

    def _draft_outcomes(
        self,
        topic: str,
        audience: str,
        standards: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "text": f"Students will be able to define key concepts in {topic}.",
                "bloom_level": "remember",
                "standards": [s.get("code", "") for s in standards[:1]],
            },
            {
                "text": f"Students will be able to analyze problems in {topic}.",
                "bloom_level": "analyze",
                "standards": [s.get("code", "") for s in standards[1:2]],
            },
            {
                "text": f"Students will be able to create solutions applying {topic} principles.",
                "bloom_level": "create",
                "standards": [],
            },
        ]

    def _draft_modules(
        self,
        topic: str,
        duration_weeks: int,
        outcomes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        modules_per_course = min(duration_weeks, 12)
        return [
            {
                "title": f"Module {i+1}: {topic} — Part {i+1}",
                "duration": "1 week",
                "outcomes": [f"outcome-{(i % len(outcomes)) + 1}"],
            }
            for i in range(modules_per_course)
        ]

    def _draft_syllabus(
        self,
        topic: str,
        audience: str,
        duration_weeks: int,
        outcomes: list[dict[str, Any]],
        modules: list[dict[str, Any]],
        constraints: str | None,
    ) -> str:
        outcomes_md = "\n".join(
            f"- {o['text']} (Bloom's: {o['bloom_level']})" for o in outcomes
        )
        modules_md = "\n".join(
            f"- **{m['title']}** ({m['duration']})" for m in modules
        )
        constraints_section = f"\n## Constraints\n{constraints}\n" if constraints else ""

        return f"""# {topic}

## Course Information
- **Audience:** {audience}
- **Duration:** {duration_weeks} weeks
{constraints_section}
## Learning Outcomes
{outcomes_md}

## Module Schedule
{modules_md}

## Assessment Plan
*To be determined — alignment matrix generated separately.*

## Course Policies
*Draft — faculty to review and customize.*
"""
