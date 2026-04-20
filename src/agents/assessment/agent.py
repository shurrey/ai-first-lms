"""Assessment sub-agent — generates and validates assessments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

# MCP tools this agent is allowed to use (from manifest).
ALLOWED_TOOLS = [
    "questions.search_bank",
    "questions.create",
    "standards.lookup",
    "content.retrieve",
    "graph.node_for_outcome",
]

# Bloom's taxonomy levels ordered by cognitive complexity.
BLOOM_LEVELS = [
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
]

# Mapping from difficulty to typical Bloom's range.
_DIFFICULTY_BLOOM_MAP: dict[str, list[str]] = {
    "intro": ["remember", "understand"],
    "moderate": ["apply", "analyze"],
    "advanced": ["evaluate", "create"],
}


class AssessmentAgent(BaseAgent):
    """Assessment generation and validation agent for faculty."""

    name = "assessment"

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
        question_types: list[str] = inputs["question_types"]
        count: int = inputs["count"]
        difficulty: str = inputs.get("difficulty", "moderate")
        include_rubric: bool = inputs.get("include_rubric", False)

        warnings: list[str] = []

        # Step 1: Search existing question bank to avoid duplication
        existing_questions: list[dict] = []
        for topic in topic_or_nodes:
            bank_results = await tools.call(
                "questions.search_bank", query=topic
            )
            existing_questions.extend(bank_results.get("questions", []))

        if existing_questions:
            warnings.append(
                f"Found {len(existing_questions)} existing item(s) in the "
                f"question bank for the requested topics. Review for reuse."
            )

        # Step 2: Retrieve content for each topic to ground questions
        content_parts: list[str] = []
        for topic in topic_or_nodes:
            content = await tools.call("content.retrieve", node_id=topic)
            if content and content.get("body_md"):
                content_parts.append(
                    wrap_user_content(content["body_md"])
                )

        # Step 3: Look up graph nodes for outcome alignment
        aligned_nodes: list[dict] = []
        for topic in topic_or_nodes:
            candidates = await tools.call(
                "graph.node_for_outcome",
                outcome_description=topic,
                top_k=3,
            )
            aligned_nodes.extend(candidates.get("candidates", []))

        # Step 4: Look up standards for alignment
        standards_results = await tools.call(
            "standards.lookup", framework="default", query=", ".join(topic_or_nodes)
        )
        available_standards = standards_results.get("standards", [])

        # Step 5: Generate questions
        questions = self._generate_questions(
            topic_or_nodes=topic_or_nodes,
            question_types=question_types,
            count=count,
            difficulty=difficulty,
            aligned_nodes=aligned_nodes,
            available_standards=available_standards,
            content_parts=content_parts,
            warnings=warnings,
        )

        # Step 6: Build rubric if requested
        rubric = None
        if include_rubric:
            rubric = self._build_rubric(topic_or_nodes, question_types)

        return {
            "questions": questions,
            "rubric": rubric,
            "warnings": warnings,
        }

    def _generate_questions(
        self,
        *,
        topic_or_nodes: list[str],
        question_types: list[str],
        count: int,
        difficulty: str,
        aligned_nodes: list[dict],
        available_standards: list[Any],
        content_parts: list[str],
        warnings: list[str],
    ) -> list[dict]:
        """Generate assessment questions.

        In production this is replaced by the Claude API call. This
        placeholder ensures the output shape is correct for testing.
        """
        questions: list[dict] = []
        node_ids = [n.get("node_id", n.get("id", "")) for n in aligned_nodes]
        standard_codes = [
            s.get("code", "") for s in available_standards if isinstance(s, dict)
        ]

        for i in range(count):
            q_type = question_types[i % len(question_types)]
            bloom = self._bloom_for_difficulty(difficulty, i)
            q_difficulty = difficulty if difficulty != "mixed" else self._mixed_difficulty(i)

            question: dict[str, Any] = {
                "stem": self._make_stem(topic_or_nodes, q_type, i),
                "type": q_type,
                "answer_key": self._make_answer_key(q_type, i),
                "bloom_level": bloom,
                "difficulty": q_difficulty,
                "aligned_nodes": node_ids[:2] if node_ids else [],
                "aligned_standards": standard_codes[:1] if standard_codes else [],
            }

            if q_type == "mcq":
                question["options"] = self._make_mcq_options(topic_or_nodes, i)

            if not question["aligned_nodes"]:
                warnings.append(
                    f"Question {i + 1}: no graph node alignment found. "
                    f"Manual alignment recommended."
                )

            questions.append(question)

        return questions

    def _bloom_for_difficulty(self, difficulty: str, index: int) -> str:
        """Select a Bloom's level appropriate for the requested difficulty."""
        if difficulty == "mixed":
            return BLOOM_LEVELS[index % len(BLOOM_LEVELS)]
        bloom_range = _DIFFICULTY_BLOOM_MAP.get(difficulty, ["apply", "analyze"])
        return bloom_range[index % len(bloom_range)]

    def _mixed_difficulty(self, index: int) -> str:
        """Cycle through difficulties for mixed-mode."""
        cycle = ["intro", "moderate", "advanced"]
        return cycle[index % len(cycle)]

    def _make_stem(self, topics: list[str], q_type: str, index: int) -> str:
        """Build a placeholder question stem."""
        topic_str = ", ".join(topics)
        if q_type == "mcq":
            return f"Which of the following best describes a key concept related to {topic_str}? (Question {index + 1})"
        if q_type == "short_answer":
            return f"Explain the significance of {topic_str} in your own words. (Question {index + 1})"
        if q_type == "essay":
            return f"Discuss the implications and applications of {topic_str}. Support your argument with examples. (Question {index + 1})"
        if q_type == "code":
            return f"Write a function that demonstrates your understanding of {topic_str}. Include test cases. (Question {index + 1})"
        return f"Question about {topic_str}. (Question {index + 1})"

    def _make_answer_key(self, q_type: str, index: int) -> str:
        """Build a placeholder answer key."""
        if q_type == "mcq":
            options = ["A", "B", "C", "D"]
            return options[index % len(options)]
        if q_type == "code":
            return "def solution(): pass  # See rubric for evaluation criteria"
        return "See rubric for evaluation criteria."

    def _make_mcq_options(self, topics: list[str], index: int) -> list[str]:
        """Build placeholder MCQ options with distractors."""
        topic_str = topics[0] if topics else "the topic"
        return [
            f"A) A correct statement about {topic_str}",
            f"B) A common misconception about {topic_str}",
            f"C) An unrelated but plausible-sounding claim",
            f"D) A partially correct statement missing a key detail",
        ]

    def _build_rubric(
        self, topics: list[str], question_types: list[str]
    ) -> dict[str, Any]:
        """Build a draft rubric.

        In production this is replaced by the Claude API call.
        """
        topic_str = ", ".join(topics)
        criteria: list[dict[str, Any]] = []

        if "essay" in question_types or "short_answer" in question_types:
            criteria.append({
                "name": "Content Accuracy",
                "weight": 40,
                "levels": {
                    "excellent": f"Demonstrates thorough understanding of {topic_str} with accurate details.",
                    "proficient": "Mostly accurate with minor gaps.",
                    "developing": "Partially correct with notable misconceptions.",
                    "beginning": "Significant inaccuracies or missing content.",
                },
            })
            criteria.append({
                "name": "Explanation Quality",
                "weight": 30,
                "levels": {
                    "excellent": "Clear, well-organized explanation with supporting examples.",
                    "proficient": "Generally clear with some supporting detail.",
                    "developing": "Unclear in places, limited supporting detail.",
                    "beginning": "Disorganized or missing explanation.",
                },
            })
            criteria.append({
                "name": "Use of Terminology",
                "weight": 30,
                "levels": {
                    "excellent": "Precise and consistent use of domain terminology.",
                    "proficient": "Generally correct terminology use.",
                    "developing": "Some terminology misuse or omission.",
                    "beginning": "Missing or incorrect terminology.",
                },
            })

        if "code" in question_types:
            criteria.append({
                "name": "Correctness",
                "weight": 50,
                "levels": {
                    "excellent": "Code produces correct output for all test cases.",
                    "proficient": "Code is mostly correct with minor edge-case failures.",
                    "developing": "Code runs but produces incorrect output for some inputs.",
                    "beginning": "Code does not run or is fundamentally incorrect.",
                },
            })
            criteria.append({
                "name": "Code Quality",
                "weight": 25,
                "levels": {
                    "excellent": "Clean, well-documented, follows best practices.",
                    "proficient": "Readable with minor style issues.",
                    "developing": "Functional but poorly organized.",
                    "beginning": "Unreadable or severely disorganized.",
                },
            })
            criteria.append({
                "name": "Test Coverage",
                "weight": 25,
                "levels": {
                    "excellent": "Comprehensive test cases including edge cases.",
                    "proficient": "Good test coverage of main scenarios.",
                    "developing": "Minimal test cases.",
                    "beginning": "No test cases provided.",
                },
            })

        if not criteria:
            criteria.append({
                "name": "Accuracy",
                "weight": 100,
                "levels": {
                    "excellent": "Fully correct response.",
                    "proficient": "Mostly correct.",
                    "developing": "Partially correct.",
                    "beginning": "Incorrect.",
                },
            })

        return {
            "title": f"Assessment Rubric: {topic_str}",
            "criteria": criteria,
        }
