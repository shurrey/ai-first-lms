"""Course brief generator — auto-summary when a session starts."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

import anthropic
import httpx

logger = logging.getLogger(__name__)

_MCP_SERVERS = {
    "roster": "http://mcp-roster:7002",
    "assessments": "http://mcp-assessments:7003",
    "content": "http://mcp-content:7001",
}

COACHING_SYSTEM_PROMPT = """\
You are the Tutor in an AI-native LMS. A student just opened their course.
Write a brief, warm, proactive greeting (2-4 sentences).
Be specific about their real data — mention their name, scores, upcoming work.
Highlight the most urgent or impactful item.
End with a concrete offer to help with something specific.
Do NOT use JSON. Write plain markdown only.
Do NOT use emojis excessively — one or two is fine.
"""


class BriefGatherer(Protocol):
    """Protocol for persona-specific data gathering."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]: ...

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]: ...


async def _call_mcp(server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and return parsed JSON result."""
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    base_url = _MCP_SERVERS.get(server, "")
    if not base_url:
        return {"error": f"Unknown server: {server}"}
    try:
        async with sse_client(f"{base_url}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                for item in result.content:
                    if hasattr(item, "text"):
                        return json.loads(item.text)
                return {}
    except Exception as exc:
        logger.warning("MCP call %s failed: %s", tool, exc)
        return {"error": str(exc)}


class StudentBriefGatherer:
    """Gathers brief data for a student persona."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]:
        student_ctx = await _call_mcp(
            "roster", "roster.get_student_context",
            {"person_id": person_id, "course_id": course_id},
        )
        evidence = await _call_mcp(
            "assessments", "assessments.list_recent_evidence",
            {"person_id": person_id, "course_id": course_id},
        )
        modules = await _call_mcp(
            "content", "content.list_modules",
            {"course_id": course_id},
        )

        return {
            "student_ctx": student_ctx,
            "evidence": evidence,
            "modules": modules,
        }

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        student_ctx = raw_data.get("student_ctx", {})
        evidence_data = raw_data.get("evidence", {})
        modules_data = raw_data.get("modules", {})

        student_name = student_ctx.get("display_name", "Student")
        course_title = student_ctx.get("course_title", "")

        evidence_list = evidence_data.get("evidence", evidence_data.get("recent_evidence", []))
        assignments = []
        scores = []
        for ev in evidence_list:
            title = ev.get("title", ev.get("kind", "Unknown"))
            score = ev.get("score")
            assignments.append({
                "title": title,
                "status": "attempted" if score is not None else "not_started",
                "score": round(score, 2) if score is not None else None,
            })
            if score is not None:
                scores.append(score)

        module_list = modules_data.get("modules", [])
        total_modules = len(module_list)

        avg_score = round(sum(scores) / len(scores), 2) if scores else 0

        suggested_actions = []
        if assignments:
            worst = min(
                (a for a in assignments if a["score"] is not None),
                key=lambda a: a["score"],
                default=None,
            )
            if worst and worst["score"] is not None and worst["score"] < 0.5:
                suggested_actions.append({
                    "label": f"Review: {worst['title']}",
                    "prompt": f"Help me understand what I got wrong on {worst['title']}",
                })
        suggested_actions.append({
            "label": "Find my weak spots",
            "prompt": "What am I weakest at in this course?",
        })
        suggested_actions.append({
            "label": "Study next topic",
            "prompt": "What should I study next?",
        })

        return {
            "persona": "student",
            "student_name": student_name,
            "course_title": course_title,
            "current_module": {
                "title": module_list[0]["title"] if module_list else "Unknown",
                "index": 1,
                "total": total_modules,
            },
            "assignments": assignments[:10],
            "stats": {
                "avg_score": avg_score,
                "submissions_count": len(scores),
                "total_assignments": len(assignments),
            },
            "suggested_actions": suggested_actions,
        }


class BriefGenerator:
    """Generates a course brief (card + coaching message) for any persona."""

    _gatherers: dict[str, BriefGatherer] = {
        "student": StudentBriefGatherer(),
    }

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            http_client=httpx.AsyncClient(verify=False),
        )

    async def generate(
        self,
        persona: str,
        person_id: str,
        course_id: str,
        turn_id: str,
        turn_store: Any,
    ) -> None:
        gatherer = self._gatherers.get(persona)
        if not gatherer:
            await turn_store.update_status(turn_id, "completed")
            return

        try:
            raw_data = await gatherer.gather(person_id, course_id)
            card = gatherer.build_card(raw_data)

            chat_msg = await self._coaching_message(raw_data)

            events = [
                {"event": "brief_card", "payload": card},
                {
                    "event": "final",
                    "payload": {
                        "answer_markdown": chat_msg,
                        "artifacts": [],
                        "cost_usd": 0.0,
                        "tokens": 0,
                        "wall_time_ms": 0.0,
                    },
                },
            ]
            await turn_store.add_events(turn_id, events)
            await turn_store.update_status(turn_id, "completed")

        except Exception as exc:
            logger.exception("Brief generation failed: %s", exc)
            await turn_store.add_events(turn_id, [{
                "event": "final",
                "payload": {
                    "answer_markdown": "Welcome to your course! Ask me anything to get started.",
                    "artifacts": [],
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "wall_time_ms": 0.0,
                },
            }])
            await turn_store.update_status(turn_id, "completed")

    async def _coaching_message(self, raw_data: dict[str, Any]) -> str:
        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                system=COACHING_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"Student data:\n{json.dumps(raw_data, indent=2, default=str)}",
                }],
                max_tokens=300,
            )
            return response.content[0].text
        except Exception as exc:
            logger.warning("Coaching message generation failed: %s", exc)
            return "Welcome to your course! I'm your tutor — ask me anything to get started."
