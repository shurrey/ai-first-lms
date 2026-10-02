"""Podcast generation — personalized audio learning from skill content."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from engine.http import make_anthropic_client, make_sync_http_client

logger = logging.getLogger(__name__)

AUDIO_DIR = Path("/app/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Fish Audio voice IDs — set these to actual voice reference IDs from fish.audio
HOST_VOICE_ID = os.environ.get("FISH_AUDIO_HOST_VOICE", "")
EXPERT_VOICE_ID = os.environ.get("FISH_AUDIO_EXPERT_VOICE", "")
FISH_AUDIO_API_KEY = os.environ.get("FISH_AUDIO_API_KEY", "")

PODCAST_SCRIPT_PROMPT = """\
You are creating a podcast script for an educational audio lesson. The student is learning {course_title} and is currently working on these concepts:

{concept_details}

Student context:
- Mastery progress: {mastery_summary}
- Learner profile: {learner_profile}

Generate a conversational podcast script between two speakers:
- HOST: Enthusiastic, curious, asks great questions, bridges between topics. Think of a podcast host who genuinely wants to understand.
- EXPERT: Knowledgeable, patient, uses great analogies and examples. Explains clearly without being condescending.

Requirements:
- 5-8 minutes of content (roughly 800-1200 words)
- Focus on the concepts listed above
- Reference what the student already knows as foundation
- Address common misconceptions from the skill content
- Make it feel like a real conversation, not a script reading
- Include moments of "aha" and genuine engagement
- End with a summary of key takeaways

Format each line as:
HOST: [dialogue]
EXPERT: [dialogue]

Write ONLY the dialogue. No stage directions, no [laughs], no meta-commentary.
"""


async def generate_podcast_script(
    concepts: list[dict[str, Any]],
    course_title: str,
    mastery_summary: str,
    learner_profile: str,
) -> str:
    """Generate a podcast script from concept skill content using Claude."""
    client = make_anthropic_client()

    concept_details = ""
    for c in concepts:
        concept_details += f"\n### {c['title']}\n{c.get('body_md', '')[:1000]}\n"

    prompt = PODCAST_SCRIPT_PROMPT.format(
        course_title=course_title,
        concept_details=concept_details,
        mastery_summary=mastery_summary,
        learner_profile=learner_profile or "No profile yet",
    )

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def parse_script(script: str) -> list[dict[str, str]]:
    """Parse a HOST:/EXPERT: script into segments."""
    segments = []
    current_speaker = None
    current_text = []

    for line in script.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("HOST:"):
            if current_speaker and current_text:
                segments.append({"speaker": current_speaker, "text": " ".join(current_text)})
            current_speaker = "host"
            current_text = [line[5:].strip()]
        elif line.startswith("EXPERT:"):
            if current_speaker and current_text:
                segments.append({"speaker": current_speaker, "text": " ".join(current_text)})
            current_speaker = "expert"
            current_text = [line[7:].strip()]
        else:
            if current_speaker:
                current_text.append(line)

    if current_speaker and current_text:
        segments.append({"speaker": current_speaker, "text": " ".join(current_text)})

    return segments


async def render_audio(segments: list[dict[str, str]], podcast_id: str) -> str:
    """Render podcast segments to audio using Fish Audio S2."""
    if not FISH_AUDIO_API_KEY:
        # Fallback: save the script as a text file for demo purposes
        logger.warning("FISH_AUDIO_API_KEY not set — saving script only")
        script_path = AUDIO_DIR / f"{podcast_id}.txt"
        with open(script_path, "w") as f:
            for seg in segments:
                f.write(f"{seg['speaker'].upper()}: {seg['text']}\n\n")
        return f"/audio/{podcast_id}.txt"

    def _render_sync() -> str:
        """Sync TTS rendering — runs in a thread to avoid blocking the event loop."""
        from fish_audio_sdk import Session, TTSRequest

        session = Session(apikey=FISH_AUDIO_API_KEY)
        # The SDK builds its own httpx.Client with certifi; swap in one that verifies via the OS store.
        session._sync_client = make_sync_http_client(
            base_url=session._base_url,
            headers=dict(session._sync_client.headers),
            timeout=None,
        )

        audio_chunks: list[bytes] = []

        voice_map = {
            "host": HOST_VOICE_ID,
            "expert": EXPERT_VOICE_ID,
        }

        for i, seg in enumerate(segments):
            voice_id = voice_map.get(seg["speaker"], HOST_VOICE_ID)
            if not voice_id:
                logger.warning("No voice ID for %s, skipping", seg["speaker"])
                continue

            logger.info("Rendering segment %d/%d (%s)", i + 1, len(segments), seg["speaker"])
            result = session.tts(TTSRequest(
                text=seg["text"],
                reference_id=voice_id,
                format="mp3",
            ))

            for chunk in result:
                audio_chunks.append(chunk)

        # Concatenate all audio chunks
        audio_path = AUDIO_DIR / f"{podcast_id}.mp3"
        with open(audio_path, "wb") as f:
            for chunk in audio_chunks:
                f.write(chunk)

        logger.info("Podcast rendered: %s (%d segments, %d bytes)", podcast_id, len(segments), audio_path.stat().st_size)
        return f"/audio/{podcast_id}.mp3"

    try:
        # Run sync TTS in a thread so the event loop stays free for chat
        return await asyncio.to_thread(_render_sync)

    except Exception as exc:
        logger.exception("Fish Audio rendering failed: %s", exc)
        # Fallback to text
        script_path = AUDIO_DIR / f"{podcast_id}.txt"
        with open(script_path, "w") as f:
            for seg in segments:
                f.write(f"{seg['speaker'].upper()}: {seg['text']}\n\n")
        return f"/audio/{podcast_id}.txt"


async def generate_podcast(
    concepts: list[dict[str, Any]],
    course_title: str,
    mastery_summary: str,
    learner_profile: str,
) -> dict[str, Any]:
    """Full podcast pipeline: script generation → audio rendering."""
    podcast_id = str(uuid.uuid4())[:8]

    # Generate script
    script = await generate_podcast_script(
        concepts, course_title, mastery_summary, learner_profile,
    )

    # Parse into segments
    segments = parse_script(script)
    if not segments:
        return {"error": "Failed to generate podcast script"}

    # Render audio
    audio_url = await render_audio(segments, podcast_id)

    return {
        "podcast_id": podcast_id,
        "audio_url": audio_url,
        "script": script,
        "segment_count": len(segments),
        "title": f"Your personalized lesson: {', '.join(c['title'] for c in concepts[:3])}",
    }
