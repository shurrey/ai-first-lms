"""Interpret step — LLM-backed intent extraction (SPEC §4.1 step 1)."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import anthropic
import httpx

from engine.graph.state import OrchestratorState

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7

INTERPRET_SYSTEM_PROMPT = """\
You are the intent classifier for an AI-First LMS orchestrator. Given the user's \
message and their persona (student/faculty/advisor/admin), extract a structured intent.

Return valid JSON with these fields:
- action: string — what the user wants (explain, quiz, grade, draft, analyze, advise, scan, etc.)
- agent: string — which agent to invoke (one of: tutor, course_architect, content_generator, \
assessment, grading_assistant, early_alert, advising, accessibility, engagement_analyst, communication)
- parameters: object — any parameters extracted from the message
- confidence: float 0-1 — how confident you are in this interpretation
- needs_clarification: boolean — true if the intent is ambiguous
- clarification_reason: string | null — why clarification is needed

Agent routing guide:
- tutor: the default student-facing agent. Handles explaining concepts, Socratic tutoring, \
quizzing, practice problems, study help, AND student questions about their assignments, \
grades, progress, and course content. If a STUDENT is asking, tutor is almost always right.
- assessment: for FACULTY/DESIGNERS creating assessments, question banks, rubrics. NOT for students checking their assignments.
- grading_assistant: for FACULTY grading submissions, providing feedback on student work
- advising: degree requirements, course planning, prerequisites, graduation timelines
- course_architect: for FACULTY designing courses, module structure, learning objectives
- content_generator: creating learning materials, practice problems, examples
- early_alert: for FACULTY/ADVISORS identifying at-risk students, engagement warnings
- accessibility: accessibility audits, accommodations, WCAG compliance
- engagement_analyst: for FACULTY viewing participation analytics, engagement metrics
- communication: messages, announcements, notifications

Key routing rules:
- Student asking about assignments, grades, progress → tutor (NOT assessment)
- Faculty creating quizzes or rubrics → assessment
- "What courses should I take next semester?" → advising

MULTI-AGENT actions (set action to exactly these strings when the request needs multiple agents):
- "identify_and_help": find struggling students AND create study guides AND send messages → uses early_alert → content_generator → communication
- "quiz_generation": create a quiz WITH supporting study materials → uses content_generator → assessment
- "syllabus_draft": draft a course structure WITH supporting content → uses course_architect → content_generator
- "risk_analysis": analyze at-risk students AND engagement trends simultaneously → uses early_alert + engagement_analyst

For multi-agent actions, set the action to the pattern name above and include "agents" in parameters \
listing the agents involved. Example:
{"action": "identify_and_help", "agent": "early_alert", "parameters": {"agents": ["early_alert", "content_generator", "communication"]}, ...}

Consider the persona when choosing the agent. Students typically interact with tutor, \
assessment, content_generator, and advising. Faculty interact with all agents.

Return ONLY valid JSON, no markdown fences.
"""


class LLMClient(Protocol):
    """Protocol for LLM client to allow easy mocking."""

    async def create_message(
        self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> str: ...


class AnthropicLLMClient:
    """Real Anthropic API client."""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            http_client=httpx.AsyncClient(verify=False),
        )

    async def create_message(
        self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> str:
        response = await self._client.messages.create(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.content[0].text


# Module-level client, replaceable for testing
_llm_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Set the LLM client (used for dependency injection in tests)."""
    global _llm_client  # noqa: PLW0603
    _llm_client = client


def get_llm_client() -> LLMClient:
    global _llm_client  # noqa: PLW0603
    if _llm_client is None:
        _llm_client = AnthropicLLMClient()
    return _llm_client


async def interpret(state: OrchestratorState) -> OrchestratorState:
    """Extract structured intent from user message using Claude."""
    message = state.get("current_message", "")
    persona = state.get("persona", "student")
    course_id = state.get("course_id", "")
    conversation = state.get("conversation", [])

    client = get_llm_client()

    # Build conversation context for short/ambiguous messages like "yes"
    context_lines = []
    if conversation:
        # Include last 2 exchanges for context
        recent = conversation[-4:]
        for turn in recent:
            role = turn.get("role", "")
            content = turn.get("content", "")
            # Truncate long messages to keep prompt small
            if len(content) > 300:
                content = content[:300] + "..."
            context_lines.append(f"[{role}]: {content}")

    context_block = "\n".join(context_lines)
    user_prompt = f"Persona: {persona}\nCourse: {course_id}"
    if context_block:
        user_prompt += f"\n\nRecent conversation:\n{context_block}"
    user_prompt += f"\n\nCurrent message: {message}"

    raw_response = await client.create_message(
        model="claude-sonnet-4-6",
        system=INTERPRET_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=512,
    )

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM interpretation response: %s", raw_response)
        parsed = {
            "action": "unknown",
            "agent": "tutor",
            "parameters": {},
            "confidence": 0.0,
            "needs_clarification": True,
            "clarification_reason": "Could not parse intent.",
        }

    confidence = parsed.get("confidence", 0.0)
    # Only clarify if confidence is genuinely low. If the LLM is >threshold
    # confident, proceed even if it suggests clarification — otherwise the
    # graph loops because there's no user input to break the cycle.
    needs_clarification = confidence < CONFIDENCE_THRESHOLD

    interpretation = {
        "action": parsed.get("action", "unknown"),
        "agent": parsed.get("agent", "tutor"),
        "parameters": parsed.get("parameters", {}),
        "confidence": confidence,
    }

    events = list(state.get("events_emitted", []))
    events.append({
        "event": "reasoning",
        "payload": {
            "step": "interpret",
            "text": f"Intent: {interpretation['action']} → agent: {interpretation['agent']} "
                    f"(confidence: {confidence:.2f})",
        },
    })

    return {
        **state,
        "interpretation": interpretation,
        "needs_clarification": needs_clarification,
        "clarification": parsed.get("clarification_reason") if needs_clarification else None,
        "events_emitted": events,
    }
