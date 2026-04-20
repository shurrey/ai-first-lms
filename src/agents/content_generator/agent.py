"""Content Generator sub-agent — generates learning materials grounded in course content."""

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
    "content.save_draft",
    "standards.lookup",
    "graph.subgraph",
]

# Valid format types this agent can produce.
VALID_FORMATS = frozenset([
    "summary",
    "study_guide",
    "worked_example",
    "reading_guide",
    "slide_deck_outline",
    "practice_problems",
])

VALID_READING_LEVELS = frozenset([
    "middle_school",
    "high_school",
    "intro_undergrad",
    "undergrad",
    "graduate",
])

VALID_LENGTHS = frozenset(["brief", "standard", "long"])


class ContentGeneratorAgent(BaseAgent):
    """Generates learning materials grounded in course content."""

    name = "content_generator"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        topic_or_nodes: list[str] = inputs["topic_or_nodes"]
        fmt: str = inputs["format"]
        reading_level: str = inputs.get("reading_level", "intro_undergrad")
        length: str = inputs.get("length", "standard")
        audience: str = inputs.get("audience", "student")

        if fmt not in VALID_FORMATS:
            raise ValueError(f"Invalid format '{fmt}'. Must be one of: {sorted(VALID_FORMATS)}")

        # Step 1: Gather source material via tools
        context_parts: list[str] = []
        citations: list[str] = []

        # Search for each topic/node
        for topic in topic_or_nodes:
            search_results = await tools.call(
                "content.search", query=topic, top_k=5
            )
            for item in search_results.get("results", []):
                context_parts.append(wrap_user_content(item.get("snippet", "")))
                if item["id"] not in citations:
                    citations.append(item["id"])

        # Retrieve full content for top results
        for node_id in citations[:3]:
            retrieved = await tools.call("content.retrieve", node_id=node_id)
            if retrieved and retrieved.get("body_md"):
                context_parts.append(wrap_user_content(retrieved["body_md"]))

        # Explore graph neighborhood for richer context
        if citations:
            subgraph = await tools.call(
                "graph.subgraph", root_ids=citations[:3], max_depth=1
            )
            for node in subgraph.get("nodes", []):
                node_id = node.get("id", "")
                if node_id and node_id not in citations:
                    citations.append(node_id)

        # Step 2: Generate content based on format
        content_md = self._build_content(
            fmt, topic_or_nodes, context_parts, reading_level, length, audience
        )

        # Step 3: Save draft
        draft_result = await tools.call(
            "content.save_draft",
            kind=fmt,
            title=self._build_title(fmt, topic_or_nodes),
            body_md=content_md,
            author_id=persona.person_id,
        )
        draft_id = draft_result.get("draft_id", "")

        return {
            "content_md": content_md,
            "citations": citations,
            "draft_id": draft_id,
        }

    def _build_title(self, fmt: str, topics: list[str]) -> str:
        """Build a human-readable title for the draft."""
        fmt_label = fmt.replace("_", " ").title()
        topic_str = ", ".join(topics[:3])
        if len(topics) > 3:
            topic_str += f" (+{len(topics) - 3} more)"
        return f"{fmt_label}: {topic_str}"

    def _build_content(
        self,
        fmt: str,
        topics: list[str],
        context_parts: list[str],
        reading_level: str,
        length: str,
        audience: str,
    ) -> str:
        """Assemble content based on format type.

        In production this is replaced by the Claude API call with the system
        prompt + gathered context. This placeholder ensures the output shape
        is correct for testing.
        """
        topic_str = ", ".join(topics)
        level_note = f" (reading level: {reading_level})"

        if fmt == "summary":
            return (
                f"# Summary: {topic_str}\n\n"
                f"This summary covers the key concepts of {topic_str}{level_note}.\n\n"
                f"## Key Points\n\n"
                f"- Core concept overview based on retrieved course material\n"
                f"- Important relationships and dependencies\n"
                f"- Practical applications\n\n"
                f"*Generated from {len(context_parts)} source passages.*"
            )

        if fmt == "study_guide":
            return (
                f"# Study Guide: {topic_str}\n\n"
                f"## Learning Objectives\n\n"
                f"After reviewing this guide, you should be able to explain "
                f"the core concepts of {topic_str}{level_note}.\n\n"
                f"## Key Concepts\n\n"
                f"- Definitions and terminology\n"
                f"- Core principles\n"
                f"- Common misconceptions\n\n"
                f"## Review Questions\n\n"
                f"1. What are the fundamental principles of {topic_str}?\n"
                f"2. How do these concepts relate to each other?\n\n"
                f"## Further Reading\n\n"
                f"See the cited course materials for deeper exploration.\n\n"
                f"*Generated from {len(context_parts)} source passages.*"
            )

        if fmt == "worked_example":
            return (
                f"# Worked Example: {topic_str}\n\n"
                f"## Problem Statement\n\n"
                f"Consider the following problem involving {topic_str}{level_note}.\n\n"
                f"## Step-by-Step Solution\n\n"
                f"**Step 1:** Identify the key elements.\n\n"
                f"**Step 2:** Apply the relevant principles.\n\n"
                f"**Step 3:** Verify the result.\n\n"
                f"## Common Mistakes\n\n"
                f"- Watch out for edge cases\n"
                f"- Double-check your assumptions\n\n"
                f"*Generated from {len(context_parts)} source passages.*"
            )

        if fmt == "reading_guide":
            return (
                f"# Reading Guide: {topic_str}\n\n"
                f"## Before You Read\n\n"
                f"Familiarize yourself with the prerequisites for {topic_str}{level_note}.\n\n"
                f"## While Reading\n\n"
                f"- Pay attention to key definitions\n"
                f"- Note relationships between concepts\n"
                f"- Mark passages you find unclear for discussion\n\n"
                f"## After Reading\n\n"
                f"- Summarize the main argument in your own words\n"
                f"- Identify three key takeaways\n\n"
                f"*Generated from {len(context_parts)} source passages.*"
            )

        if fmt == "slide_deck_outline":
            return (
                f"# Slide Deck Outline: {topic_str}\n\n"
                f"## Slide 1 — Title\n"
                f"**{topic_str}**\n\n"
                f"## Slide 2 — Overview\n"
                f"Key topics to cover{level_note}\n\n"
                f"## Slide 3 — Core Concepts\n"
                f"- Main ideas from course material\n"
                f"- Supporting evidence\n\n"
                f"## Slide 4 — Examples\n"
                f"- Worked example from source material\n\n"
                f"## Slide 5 — Summary & Questions\n"
                f"- Key takeaways\n"
                f"- Discussion questions\n\n"
                f"*Generated from {len(context_parts)} source passages.*"
            )

        if fmt == "practice_problems":
            return (
                f"# Practice Problems: {topic_str}\n\n"
                f"## Problem 1 — Recognition\n"
                f"Identify the key concept in {topic_str}{level_note}.\n"
                f"*Hint: Review the definitions section.*\n\n"
                f"## Problem 2 — Application\n"
                f"Apply the principles of {topic_str} to a new scenario.\n"
                f"*Hint: Think about real-world applications.*\n\n"
                f"## Problem 3 — Analysis\n"
                f"Compare and contrast two aspects of {topic_str}.\n"
                f"*Hint: Look for similarities and differences.*\n\n"
                f"## Problem 4 — Synthesis\n"
                f"Combine concepts from {topic_str} to solve a novel problem.\n"
                f"*Hint: Draw on multiple source materials.*\n\n"
                f"*Generated from {len(context_parts)} source passages.*"
            )

        # Should never reach here due to validation, but be safe
        raise ValueError(f"Unhandled format: {fmt}")
