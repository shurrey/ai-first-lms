"""Grading Assistant sub-agent — drafts rubric-based scores and feedback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

# MCP tools this agent is allowed to use (from manifest).
ALLOWED_TOOLS = [
    "submissions.get",
    "rubrics.get",
    "grades.draft",
    "grades.commit",  # gated — requires faculty approval via orchestrator
]


class GradingAssistantAgent(BaseAgent):
    """Drafts rubric-based scores and feedback for student submissions."""

    name = "grading_assistant"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        submission_ids: list[str] = inputs["submission_ids"]
        rubric_id: str = inputs["rubric_id"]
        exemplars: list[str] | None = inputs.get("exemplars")

        # Step 1: Fetch the rubric (once for all submissions)
        rubric = await tools.call("rubrics.get", rubric_id=rubric_id)
        criteria = rubric.get("criteria", [])

        if not criteria:
            return {
                "drafts": [],
                "error": "Rubric has no criteria defined.",
            }

        # Step 2: Fetch and score each submission
        drafts: list[dict[str, Any]] = []
        for sub_id in submission_ids:
            submission = await tools.call("submissions.get", submission_id=sub_id)
            draft = self._score_submission(submission, criteria, persona)
            drafts.append(draft)

            # Step 3: Save each draft via the grades.draft tool
            await tools.call(
                "grades.draft",
                submission_id=sub_id,
                rubric_id=rubric_id,
                scores=draft["scores"],
                feedback=draft["feedback"],
                holistic_md=draft["holistic_md"],
                graded_by=persona.person_id,
            )

        return {"drafts": drafts}

    def _score_submission(
        self,
        submission: dict[str, Any],
        criteria: list[dict[str, Any]],
        persona: PersonaContext,
    ) -> dict[str, Any]:
        """Score a single submission against all rubric criteria.

        In production this is replaced by a Claude API call with the system
        prompt, rubric, and submission content. This placeholder produces
        deterministic output so the scaffold is testable without an API key.
        """
        sub_id = submission.get("id", "unknown")
        body = submission.get("body_md", "")
        student_name = submission.get("student_name", "the student")
        wrapped_body = wrap_user_content(body)

        scores: dict[str, int] = {}
        feedback: dict[str, str] = {}
        flags: list[str] = []

        for criterion in criteria:
            crit_name = criterion["name"]
            max_points = criterion.get("max_points", 10)
            # Placeholder scoring: assign 70% of max by default
            score = int(max_points * 0.7)
            scores[crit_name] = score
            feedback[crit_name] = (
                f"{student_name}, your work on '{crit_name}' demonstrates understanding "
                f"of the core concepts. To improve, consider providing more specific evidence."
            )

            # Flag boundary scores
            if score <= criterion.get("min_points", 0):
                flags.append(f"boundary_score: {crit_name} at minimum")

        # Check for empty or very short submissions
        if len(body.strip()) < 50:
            flags.append("short_submission: body is under 50 characters")

        holistic_md = (
            f"{student_name}, this submission shows a solid foundation. "
            f"The strongest areas are in meeting the core requirements. "
            f"For future work, focus on depth of analysis and supporting evidence."
        )

        # Confidence is lower when flags are present
        confidence = 0.85 if not flags else 0.6

        return {
            "submission_id": sub_id,
            "scores": scores,
            "feedback": feedback,
            "holistic_md": holistic_md,
            "confidence": confidence,
            "flags": flags,
        }
