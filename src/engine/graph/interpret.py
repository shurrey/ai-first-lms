"""Interpret step — LLM-backed intent extraction (SPEC §4.1 step 1)."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from engine.graph.state import OrchestratorState
from engine.guardrails.registry import get_permission_matrix
from engine.http import make_anthropic_client

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7

# Fallback order when the classifier names no agent; the first one the persona may use wins.
_DEFAULT_AGENT_ORDER = ("tutor", "early_alert", "advising", "engagement_analyst", "communication")
# The agent a persona's general questions go to when the classifier names none.
_PERSONA_DEFAULT = {
    "student": "tutor",
    "faculty": "tutor",
    "advisor": "advising",
    "admin": "engagement_analyst",
    "program_lead": "engagement_analyst",
}


def _default_agent(allowed: set[str] | frozenset[str], persona: str | None = None) -> str:
    preferred = _PERSONA_DEFAULT.get(persona or "")
    if preferred in allowed:
        return preferred
    for name in _DEFAULT_AGENT_ORDER:
        if name in allowed:
            return name
    return min(allowed) if allowed else "tutor"


# Agents a user turn may reach; background agents (learning_analyst) are excluded even when a
# manifest grants them to the persona.
ROUTABLE_AGENTS = frozenset({
    "tutor", "course_architect", "content_generator", "assessment", "grading_assistant",
    "early_alert", "advising", "accessibility", "engagement_analyst", "communication",
})

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
- assessment: for FACULTY/DESIGNERS creating assessments, question banks, rubrics, \
AND reviewing credential evidence, approving badges, checking pending credentials. NOT for students checking their assignments.
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
- Faculty asking about credentials, badges, evidence, approvals → assessment
- Student asking about their earned badges or credentials → tutor
- "What courses should I take next semester?" → advising
- Student asking to build a learning path or a plan to improve a skill ("help me build a path") → advising
- If the student says "done", "bye", "I'm done for today", "that's all", "gotta go", etc. → set action to "session_end" and agent to "tutor". The tutor will handle the farewell with a reflection question.

MULTI-AGENT actions (set action to exactly these strings when the request needs multiple agents):
- "identify_and_help": find struggling students AND create study guides AND send messages → uses early_alert → content_generator → communication
- "quiz_generation": create a quiz WITH supporting study materials → uses content_generator → assessment
- "syllabus_draft": draft a course structure WITH supporting content → uses course_architect → content_generator
- "risk_analysis": analyze at-risk students AND engagement trends simultaneously → uses early_alert + engagement_analyst

For multi-agent actions, set the action to the pattern name above and include "agents" in parameters \
listing the agents involved. Example:
{"action": "identify_and_help", "agent": "early_alert", "parameters": {"agents": ["early_alert", "content_generator", "communication"]}, ...}

The user message lists the agents the persona is allowed to use. Choose only from that list; \
an agent outside it will be refused.

Return ONLY valid JSON, no markdown fences.
"""


def _constrain_agent(chosen: Any, allowed: frozenset[str], default: str, persona: str) -> str:
    """The classifier's agent if routable for this persona, else the persona's default."""
    if chosen in (None, ""):
        return default
    if isinstance(chosen, str) and chosen in allowed:
        return chosen
    logger.warning("Classifier chose agent %r, not routable for persona %s; using %s",
                   chosen, persona, default)
    return default


def _constrain_parameters(params: Any, allowed: frozenset[str], persona: str) -> dict[str, Any]:
    """`parameters` with `agents` (multi-agent plans) limited to routable agents."""
    if not isinstance(params, dict):
        return {}
    agents = params.get("agents")
    if agents is None:
        return params
    listed = agents if isinstance(agents, list) else [agents]
    kept = [a for a in listed if isinstance(a, str) and a in allowed]
    if len(kept) != len(listed):
        logger.warning("Classifier listed agents %r; dropped those not routable for persona %s",
                       agents, persona)
    return {**params, "agents": kept}


class LLMClient(Protocol):
    """Protocol for LLM client to allow easy mocking."""

    async def create_message(
        self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> str: ...


class AnthropicLLMClient:
    """Real Anthropic API client."""

    def __init__(self) -> None:
        self._client = make_anthropic_client()

    async def create_message(
        self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> str:
        text, _ = await self.create_message_with_usage(model, system, messages, max_tokens)
        return text

    async def create_message_with_usage(
        self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> tuple[str, int]:
        """Like create_message, plus total tokens (input + output) for budget charging."""
        response = await self._client.messages.create(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        return response.content[0].text, tokens


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse the classifier's JSON object; tolerates markdown fences and surrounding prose."""
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("response is not a JSON object")
    return parsed


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
    allowed = frozenset(get_permission_matrix().allowed_agents(persona)) & ROUTABLE_AGENTS
    allowed_agents = ", ".join(sorted(allowed)) or "none"
    default_agent = _default_agent(allowed, persona)
    user_prompt = f"Persona: {persona}\nAllowed agents: {allowed_agents}\nCourse: {course_id}"
    if context_block:
        user_prompt += f"\n\nRecent conversation:\n{context_block}"
    user_prompt += f"\n\nCurrent message: {message}"

    call_args = {
        "model": "claude-sonnet-4-6",
        "system": INTERPRET_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": 512,
    }
    # Clients without usage reporting (test doubles) are not charged to the budget.
    with_usage = getattr(client, "create_message_with_usage", None)
    if with_usage is not None:
        raw_response, tokens = await with_usage(**call_args)
        budget = state.get("budget")
        if budget is not None:
            # Accounting only: the gateway's next charge in dispatch halts an over-cap turn.
            budget.charge(tokens=tokens)
    else:
        raw_response = await client.create_message(**call_args)

    try:
        parsed = _parse_json_object(raw_response)
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse LLM interpretation response: %s", raw_response)
        parsed = {
            "action": "unknown",
            "agent": default_agent,
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
        "agent": _constrain_agent(parsed.get("agent"), allowed, default_agent, persona),
        "parameters": _constrain_parameters(parsed.get("parameters"), allowed, persona),
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
