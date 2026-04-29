"""Learning analyst — background post-session analysis."""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import Any

import anthropic
import httpx

logger = logging.getLogger(__name__)


async def run_session_analysis(
    session_id: str,
    person_id: str,
    course_id: str,
    deep: bool = False,
) -> None:
    """Run post-session learning analysis. Called as a background task."""
    from engine.agents.runner import _call_mcp_tool

    try:
        # Gather data
        transcript_raw = await _call_mcp_tool("roster.get_session_transcript", {"session_id": session_id})
        transcript = json.loads(transcript_raw) if isinstance(transcript_raw, str) else transcript_raw

        profile_raw = await _call_mcp_tool("roster.get_learner_profile", {"person_id": person_id})
        profile = json.loads(profile_raw) if isinstance(profile_raw, str) else profile_raw

        attestations_raw = await _call_mcp_tool("attestations.get_student_attestations", {
            "person_id": person_id, "course_id": course_id,
        })
        attestations = json.loads(attestations_raw) if isinstance(attestations_raw, str) else attestations_raw

        turns = transcript.get("turns", [])
        if not turns:
            logger.info("No turns in session %s, skipping analysis", session_id)
            return

        # Format transcript for analyst
        conv_text = "\n".join(
            f"{'Student' if t['role'] == 'user' else 'Tutor'}: {t['content'][:500]}"
            for t in turns
        )

        current_profile = profile.get("profile", "")
        att_list = attestations.get("attestations", []) if isinstance(attestations, dict) else []
        attestation_summary = ", ".join(
            f"{a.get('node_title', 'unknown')}: {a.get('level', '?')}"
            for a in att_list[:20]
        )

        # For deep review, gather additional session history
        deep_context = ""
        if deep:
            sessions_raw = await _call_mcp_tool("roster.list_student_sessions", {
                "person_id": person_id, "course_id": course_id,
            })
            sessions = json.loads(sessions_raw) if isinstance(sessions_raw, str) else sessions_raw
            prior_sessions = [s for s in sessions.get("sessions", []) if s["session_id"] != session_id][:15]

            for ps in prior_sessions[:5]:
                try:
                    pt_raw = await _call_mcp_tool("roster.get_session_transcript", {"session_id": ps["session_id"]})
                    pt = json.loads(pt_raw) if isinstance(pt_raw, str) else pt_raw
                    pt_text = "\n".join(
                        f"{'Student' if t['role'] == 'user' else 'Tutor'}: {t['content'][:200]}"
                        for t in pt.get("turns", [])[:10]
                    )
                    deep_context += f"\n--- Previous session ({ps['created_at']}) ---\n{pt_text}\n"
                except Exception:
                    pass

        # Build analyst prompt
        prompt = f"""Analyze this tutoring session and produce structured observations.

CURRENT LEARNER PROFILE:
{current_profile or "(empty — first session)"}

ATTESTATION STATE:
{attestation_summary or "(none)"}

{"PREVIOUS SESSIONS (for longitudinal analysis):" + deep_context if deep_context else ""}

CURRENT SESSION TRANSCRIPT:
{conv_text}

{"Perform a DEEP REVIEW — look for longitudinal patterns across sessions." if deep else "Perform a SHALLOW REVIEW — focus on this session only."}

Return ONLY valid JSON matching this schema:
{{
  "session_summary": "2-3 sentence summary of what happened",
  "profile_additions": "Markdown to append to the learner profile (tagged with course context)",
  "review_flag": false,
  "review_reason": null,
  "student_insights": ["plain-language insight for the student"],
  "concepts_reviewed": [{{"id": "concept-title", "outcome": "recalled|struggled|failed"}}]
}}"""

        # Load system prompt
        prompt_path = Path(__file__).resolve().parent.parent / "agents" / "learning_analyst" / "system_prompt.md"
        system = prompt_path.read_text() if prompt_path.exists() else "You are a learning analyst. Analyze the session and return JSON."

        # Call Claude — Haiku for shallow, Sonnet for deep
        model = "claude-sonnet-4-6" if deep else "claude-haiku-4-5-20251001"
        client = anthropic.AsyncAnthropic(http_client=httpx.AsyncClient(verify=False))
        response = await client.messages.create(
            model=model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        result_text = response.content[0].text.strip()

        # Parse JSON from response
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not match:
            logger.warning("Analyst returned non-JSON: %s", result_text[:200])
            return
        result = json.loads(match.group())

        # Apply results

        # 1. Session summary
        if result.get("session_summary"):
            await _call_mcp_tool("roster.update_session_summary", {
                "session_id": session_id,
                "summary": result["session_summary"],
                "review_flag": result.get("review_flag", False),
                "review_reason": result.get("review_reason"),
            })
            logger.info("Session %s summary: %s", session_id, result["session_summary"][:80])

        # 2. Profile update
        if result.get("profile_additions"):
            new_profile = current_profile
            if new_profile:
                new_profile += "\n\n" + result["profile_additions"]
            else:
                new_profile = result["profile_additions"]
            await _call_mcp_tool("roster.update_learner_profile", {
                "person_id": person_id,
                "profile_md": new_profile,
            })

        # 3. Student insights
        if result.get("student_insights"):
            await _call_mcp_tool("roster.update_student_insights", {
                "person_id": person_id,
                "insights": result["student_insights"],
            })

        # 4. Concept reviews
        for cr in result.get("concepts_reviewed", []):
            try:
                await _call_mcp_tool("roster.save_concept_review", {
                    "person_id": person_id,
                    "concept_id": cr.get("id", ""),
                    "session_id": session_id,
                    "outcome": cr.get("outcome", "recalled"),
                })
            except Exception:
                pass

        # 5. Maybe trigger deep review
        if not deep:
            should_deep = (
                result.get("review_flag")
                or random.random() < 0.20
            )
            if should_deep:
                logger.info("Triggering deep review for %s", person_id)
                import asyncio
                asyncio.create_task(run_session_analysis(
                    session_id=session_id,
                    person_id=person_id,
                    course_id=course_id,
                    deep=True,
                ))

        logger.info("Analysis complete for session %s (deep=%s)", session_id, deep)

    except Exception:
        logger.exception("Learning analyst failed for session %s", session_id)
