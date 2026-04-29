"""Podcast generation API endpoint."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

AUDIO_DIR = Path("/app/audio")


class PodcastRequest(BaseModel):
    person_id: str
    course_id: str
    session_id: str | None = None  # Used to read conversation context
    concept_ids: list[str] | None = None  # If None, auto-select from context


async def _pick_concepts_from_conversation(
    session_id: str,
    mastery_data: dict,
    turn_store: Any,
) -> list[str]:
    """Use Claude to identify which concepts the tutor has been teaching from conversation history."""
    import anthropic
    import httpx

    # Get recent conversation turns
    history = await turn_store.get_conversation_history(session_id)

    if not history:
        return []

    # Build a list of all concept names/IDs from the mastery map
    concept_list = []
    for mc in mastery_data.get("microcredentials", []):
        for mod in mc.get("modules", []):
            for c in mod.get("concepts", []):
                concept_list.append({"id": c["id"], "title": c.get("title", c["id"])})

    if not concept_list:
        return []

    # Format conversation for Claude
    conv_text = "\n".join(
        f"{'Student' if t.get('role') == 'user' else 'Tutor'}: {t.get('content', '')[:300]}"
        for t in history[-10:]  # Last 10 turns
    )

    concept_names = "\n".join(f"- {c['title']} (id: {c['id']})" for c in concept_list)

    client = anthropic.AsyncAnthropic(
        http_client=httpx.AsyncClient(verify=False),
    )

    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": f"""Based on this tutoring conversation, which concepts is the tutor currently teaching or recommending the student work on?

CONVERSATION:
{conv_text}

AVAILABLE CONCEPTS:
{concept_names}

Return ONLY a JSON array of concept IDs (max 5) that the tutor is actively teaching or just recommended. Pick the most relevant ones. If unsure, return an empty array.
Example: ["id1", "id2", "id3"]"""}],
    )

    # Parse the response
    text = response.content[0].text.strip()
    # Extract JSON array from response
    import re
    match = re.search(r'\[.*?\]', text, re.DOTALL)
    if match:
        try:
            ids = json.loads(match.group())
            # Validate IDs exist in concept list
            valid_ids = {c["id"] for c in concept_list}
            return [i for i in ids if i in valid_ids][:5]
        except json.JSONDecodeError:
            pass
    return []


def _fallback_concept_selection(mastery_data: dict) -> list[str]:
    """Fallback: pick concepts from the active microcredential."""
    emerging_ids = []
    proficient_ids = []
    active_mc_not_started = []

    active_mc_found = False
    for mc in mastery_data.get("microcredentials", []):
        if mc.get("earned"):
            continue
        has_progress = any(
            c.get("level") in ("emerging", "proficient", "mastery")
            for mod in mc.get("modules", [])
            for c in mod.get("concepts", [])
        )
        for mod in mc.get("modules", []):
            for concept in mod.get("concepts", []):
                level = concept.get("level")
                if level == "emerging":
                    emerging_ids.append(concept["id"])
                elif level == "proficient":
                    proficient_ids.append(concept["id"])
                elif level == "not_started" and has_progress and not active_mc_found:
                    active_mc_not_started.append(concept["id"])
        if has_progress:
            active_mc_found = True

    return (emerging_ids + proficient_ids + active_mc_not_started)[:5]


@router.post("/api/generate-podcast")
async def generate_podcast_endpoint(body: PodcastRequest, request: Request) -> dict[str, Any]:
    """Generate a personalized podcast for a student."""
    from engine.podcast import generate_podcast

    from engine.agents.runner import _call_mcp_tool

    # Get mastery map
    mastery_raw = await _call_mcp_tool("graph.mastery_map", {
        "person_id": body.person_id,
        "course_id": body.course_id,
    })
    mastery_data = json.loads(mastery_raw) if isinstance(mastery_raw, str) else mastery_raw

    # Select concepts: explicit > conversation-aware > fallback
    if body.concept_ids:
        target_ids = body.concept_ids
    elif body.session_id:
        # Use conversation context to pick what the tutor is teaching
        turn_store = request.app.state.turn_store
        target_ids = await _pick_concepts_from_conversation(body.session_id, mastery_data, turn_store)
        if not target_ids:
            target_ids = _fallback_concept_selection(mastery_data)
    else:
        target_ids = _fallback_concept_selection(mastery_data)

    if not target_ids:
        return {"error": "No concepts to generate podcast for"}

    # Get skill content for each concept
    concepts = []
    for cid in target_ids[:5]:  # Max 5 concepts per podcast
        skill_raw = await _call_mcp_tool("content.get_skill", {"concept_id": cid})
        skill_data = json.loads(skill_raw) if isinstance(skill_raw, str) else skill_raw
        if not skill_data.get("error"):
            concepts.append({
                "id": cid,
                "title": skill_data.get("concept_title", ""),
                "body_md": skill_data.get("body_md", ""),
            })

    if not concepts:
        return {"error": "No skill content available for selected concepts"}

    # Get learner profile
    profile_raw = await _call_mcp_tool("roster.get_learner_profile", {"person_id": body.person_id})
    profile_data = json.loads(profile_raw) if isinstance(profile_raw, str) else profile_raw
    learner_profile = profile_data.get("profile", "")

    # Generate summary
    summary = mastery_data.get("summary", {})
    mastery_summary = f"{summary.get('mastery', 0)}/{summary.get('total_concepts', 0)} mastered, {summary.get('microcredentials_earned', 0)}/{summary.get('microcredentials_total', 0)} microcredentials"

    course_title = mastery_data.get("course_title", "Course")

    # Generate the podcast
    result = await generate_podcast(
        concepts=concepts,
        course_title=course_title,
        mastery_summary=mastery_summary,
        learner_profile=learner_profile,
    )

    return result


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve generated audio files."""
    filepath = AUDIO_DIR / filename
    if not filepath.exists():
        return {"error": "Audio file not found"}

    if filename.endswith(".mp3"):
        return FileResponse(filepath, media_type="audio/mpeg")
    elif filename.endswith(".txt"):
        return FileResponse(filepath, media_type="text/plain")
    else:
        return FileResponse(filepath)
