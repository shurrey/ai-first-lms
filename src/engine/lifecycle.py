"""Session lifecycle hooks — retrieval practice, revision tracking, interleaving, reflection."""

from __future__ import annotations

import json
import logging
import random
from datetime import timedelta

from common import clock

logger = logging.getLogger(__name__)


async def get_retrieval_practice_injection(
    person_id: str, course_id: str, session_id: str
) -> str | None:
    """Generate retrieval practice context injection for session start."""
    from engine.agents.runner import _call_mcp_json

    data = await _call_mcp_json("roster.get_review_candidates", {
        "person_id": person_id,
        "course_id": course_id,
        "limit": 3,
    })
    concepts = data.get("concepts", [])

    if not concepts:
        return None

    cutoff = (clock.now() - timedelta(hours=24)).isoformat()
    candidates = [c for c in concepts if not c.get("last_reviewed") or c["last_reviewed"] < cutoff]

    if not candidates:
        return None

    titles = [c["title"] for c in candidates[:3]]
    return (
        f"RETRIEVAL_PRACTICE_CONCEPTS: {json.dumps(titles)}\n"
        "Before starting today's lesson, test recall on these concepts. "
        "No hints, no context — ask cold. "
        "Use these as mastery challenge opportunities if the student demonstrates deep understanding."
    )


def get_revision_injection(session_metadata: dict) -> str | None:
    """Generate revision loop context injection if there are pending revisions."""
    pending = session_metadata.get("revision_pending", [])
    if not pending:
        return None

    lines = ["REVISION_PENDING:"]
    for item in pending:
        lines.append(
            f'- Student previously struggled with "{item["concept_title"]}" (attempt {item["attempt"]}). '
            "Give them another attempt at specifically this aspect."
        )
    if any(item["attempt"] >= 2 for item in pending):
        lines.append("For attempt 3+, try a completely different modality (diagram, code trace, analogy).")
    return "\n".join(lines)


def get_interleaving_injection(session_metadata: dict, person_id: str) -> str | None:
    """Generate interleaving context injection if conditions are met."""
    turn_count = session_metadata.get("concept_turn_count", 0)
    current_concept = session_metadata.get("current_concept")
    proficient_concepts = session_metadata.get("proficient_concepts", [])

    if turn_count < 3 or not current_concept or len(proficient_concepts) < 2:
        return None
    if session_metadata.get("revision_pending"):
        return None

    others = [c for c in proficient_concepts if c != current_concept][:3]
    return (
        f'INTERLEAVE_OPPORTUNITY: Student has been on "{current_concept}" for {turn_count} turns. '
        f'Also proficient in: {", ".join(others)}. '
        "Consider a problem where the student must choose the right approach or combine concepts."
    )


REFLECTION_TYPES = [
    'Ask: "What was the most challenging thing we worked on today?"',
    'Ask: "Where might you use what you learned today outside this course?"',
    'Ask: "If you had to explain one thing from today to a friend, what would it be?"',
    'Ask: "What helped you understand the concepts today — the examples, the diagrams, or working through code?"',
    'Ask: "How are you feeling about your progress after today\'s session?"',
]


def get_reflection_injection() -> str:
    """Generate metacognitive reflection prompt for session end."""
    reflection = random.choice(REFLECTION_TYPES)
    return (
        f"SESSION_ENDING: {reflection} "
        "Keep it brief — one question, then close by naming what the student practiced."
    )
