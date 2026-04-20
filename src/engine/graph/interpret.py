"""Interpret step — LLM-backed intent extraction (SPEC §4.1 step 1)."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import anthropic

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

Consider the persona when choosing the agent. Students typically interact with tutor, \
content_generator, and advising. Faculty interact with all agents.

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
        self._client = anthropic.AsyncAnthropic()

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

    client = get_llm_client()
    user_prompt = f"Persona: {persona}\nMessage: {message}"

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
    needs_clarification = parsed.get("needs_clarification", False) or confidence < CONFIDENCE_THRESHOLD

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
