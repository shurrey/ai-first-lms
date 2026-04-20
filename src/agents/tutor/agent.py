"""Tutor sub-agent — Socratic tutoring over course content."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

# MCP tools this agent is allowed to use (from manifest).
ALLOWED_TOOLS = [
    "content.retrieve",
    "content.search",
    "roster.get_student_context",
    "assessments.list_recent_evidence",
    "graph.neighbors",
    "graph.path_to_mastery",
]


class TutorAgent(BaseAgent):
    """Socratic tutoring agent for students."""

    name = "tutor"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        query: str = inputs["query"]
        course_id: str = inputs["course_id"]
        mode: str = inputs.get("mode", "explain")
        student_id: str | None = inputs.get("student_id") or persona.person_id

        # Step 1: Gather context via tools
        context_parts: list[str] = []
        citations: list[str] = []

        # Always search for relevant content
        search_results = await tools.call(
            "content.search", query=query, course_id=course_id, top_k=5
        )
        for item in search_results.get("results", []):
            context_parts.append(wrap_user_content(item.get("snippet", "")))
            citations.append(item["id"])

        # Get student context if we have a student
        if student_id:
            student_ctx = await tools.call(
                "roster.get_student_context",
                person_id=student_id,
                course_id=course_id,
            )
            if student_ctx:
                context_parts.append(
                    wrap_user_content(str(student_ctx.get("recent_evidence", "")))
                )

        # Mode-specific tool calls
        if mode == "find_weakness" and student_id:
            evidence = await tools.call(
                "assessments.list_recent_evidence",
                person_id=student_id,
                since_days=14,
            )
            context_parts.append(wrap_user_content(str(evidence)))

        if mode in ("explain", "practice"):
            # Explore graph neighborhood for richer context
            if search_results.get("results"):
                first_id = search_results["results"][0]["id"]
                neighbors = await tools.call(
                    "graph.neighbors",
                    node_id=first_id,
                    direction="both",
                    depth=1,
                )
                suggested_nodes = [
                    n["id"] for n in neighbors.get("nodes", [])[:3]
                ]
            else:
                suggested_nodes = []
        else:
            suggested_nodes = []

        # Step 2: Build the response
        # In a real implementation this would call the Claude API with
        # the system prompt + gathered context. For now we assemble the
        # structured output directly so the scaffold is testable without
        # an API key.
        response_md = self._build_response(query, mode, context_parts)
        follow_ups = self._suggest_follow_ups(mode, query)

        return {
            "response_markdown": response_md,
            "citations": citations,
            "follow_ups": follow_ups,
            "suggested_nodes": suggested_nodes,
        }

    def _build_response(
        self, query: str, mode: str, context_parts: list[str]
    ) -> str:
        """Assemble a response skeleton.

        In production this is replaced by the Claude API call. This
        placeholder ensures the output shape is correct for testing.
        """
        if mode == "quiz_me":
            return f"Let's test your understanding. Based on the course material about '{query}', here's a question for you..."
        if mode == "find_weakness":
            return f"Looking at your recent work, here are the areas where you might want to focus..."
        if mode == "practice":
            return f"Here are some practice problems related to '{query}'..."
        # default: explain
        return f"Great question about '{query}'. Let me walk you through this concept..."

    def _suggest_follow_ups(self, mode: str, query: str) -> list[str]:
        """Generate contextual follow-up suggestions."""
        if mode == "explain":
            return [
                f"Can you give me a worked example of {query}?",
                f"Quiz me on {query}",
                "What should I study next?",
            ]
        if mode == "quiz_me":
            return ["Give me another question", "Explain why that's the answer", "What am I weakest at?"]
        if mode == "find_weakness":
            return ["Help me study my weakest area", "Quiz me on that topic"]
        return ["Tell me more", "Quiz me on this"]
