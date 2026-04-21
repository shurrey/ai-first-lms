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


class FacultyBriefGatherer:
    """Gathers brief data for a faculty persona."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]:
        roster = await _call_mcp(
            "roster", "roster.list_by_course",
            {"course_id": course_id},
        )
        modules = await _call_mcp(
            "content", "content.list_modules",
            {"course_id": course_id},
        )

        # Gather evidence for all students to compute class-level stats
        persons = roster.get("persons", [])
        students = [p for p in persons if "student" in p.get("roles", [])]
        all_evidence: list[dict[str, Any]] = []
        # Sample up to 10 students for evidence (avoid 50 MCP calls)
        import random
        sample = random.sample(students, min(10, len(students))) if students else []
        for student in sample:
            ev = await _call_mcp(
                "assessments", "assessments.list_recent_evidence",
                {"person_id": student["id"], "course_id": course_id},
            )
            evidence_list = ev.get("evidence", ev.get("recent_evidence", []))
            for e in evidence_list:
                e["student_name"] = student.get("display_name", "Unknown")
            all_evidence.extend(evidence_list)

        return {
            "roster": roster,
            "modules": modules,
            "all_evidence": all_evidence,
            "student_count": len(students),
            "faculty_count": len([p for p in persons if "faculty" in p.get("roles", [])]),
            "persona": "faculty",
        }

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        modules_data = raw_data.get("modules", {})
        all_evidence = raw_data.get("all_evidence", [])
        student_count = raw_data.get("student_count", 0)
        faculty_count = raw_data.get("faculty_count", 0)
        module_list = modules_data.get("modules", [])

        # Compute score distribution from sampled evidence
        student_avgs: dict[str, list[float]] = {}
        for ev in all_evidence:
            score = ev.get("score")
            name = ev.get("student_name", "Unknown")
            if score is not None:
                student_avgs.setdefault(name, []).append(score)

        # Tier distribution
        high = medium = low = at_risk = 0
        all_scores: list[float] = []
        for name, scores in student_avgs.items():
            avg = sum(scores) / len(scores)
            all_scores.append(avg)
            if avg >= 0.8:
                high += 1
            elif avg >= 0.5:
                medium += 1
            elif avg >= 0.3:
                low += 1
            else:
                at_risk += 1

        class_avg = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0
        sampled = len(student_avgs)

        # Find struggling students
        struggling = [
            {"name": name, "avg": round(sum(scores) / len(scores), 2)}
            for name, scores in student_avgs.items()
            if sum(scores) / len(scores) < 0.5
        ]
        struggling.sort(key=lambda s: s["avg"])

        return {
            "persona": "faculty",
            "student_name": "Instructor View",
            "course_title": "",
            "current_module": {
                "title": module_list[0]["title"] if module_list else "Unknown",
                "index": 1,
                "total": len(module_list),
            },
            "assignments": [],
            "stats": {
                "avg_score": class_avg,
                "submissions_count": student_count,
                "total_assignments": 0,
            },
            "suggested_actions": [
                {"label": "View class performance", "prompt": "How is my class performing overall?"},
                {"label": "Check at-risk students", "prompt": "Which students are at risk of falling behind?"},
                {"label": "Review pending submissions", "prompt": "Are there any submissions I need to grade?"},
            ],
            "extra": {
                "faculty_count": faculty_count,
                "score_distribution": {
                    "high": high,
                    "medium": medium,
                    "low": low,
                    "at_risk": at_risk,
                    "sampled": sampled,
                },
                "struggling_students": struggling[:5],
                "class_avg": class_avg,
            },
        }


class AdvisorBriefGatherer:
    """Gathers brief data for an advisor persona."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]:
        roster = await _call_mcp(
            "roster", "roster.list_by_course",
            {"course_id": course_id},
        )
        return {"roster": roster, "persona": "advisor"}

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        roster = raw_data.get("roster", {})
        students = roster.get("persons", roster.get("students", roster.get("enrollments", [])))
        student_count = len(students) if isinstance(students, list) else 0

        return {
            "persona": "advisor",
            "student_name": "Advisor View",
            "course_title": "",
            "current_module": {"title": "", "index": 0, "total": 0},
            "assignments": [],
            "stats": {
                "avg_score": 0,
                "submissions_count": student_count,
                "total_assignments": 0,
            },
            "suggested_actions": [
                {"label": "At-risk students", "prompt": "Which students in this course need attention?"},
                {"label": "Engagement overview", "prompt": "Show me engagement trends for this course"},
                {"label": "Degree progress", "prompt": "Which students are behind on degree requirements?"},
            ],
        }


class AdminBriefGatherer:
    """Gathers brief data for an admin persona."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]:
        roster = await _call_mcp(
            "roster", "roster.list_by_course",
            {"course_id": course_id},
        )
        return {"roster": roster, "persona": "admin"}

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        roster = raw_data.get("roster", {})
        students = roster.get("persons", roster.get("students", roster.get("enrollments", [])))
        student_count = len(students) if isinstance(students, list) else 0

        return {
            "persona": "admin",
            "student_name": "Admin View",
            "course_title": "",
            "current_module": {"title": "", "index": 0, "total": 0},
            "assignments": [],
            "stats": {
                "avg_score": 0,
                "submissions_count": student_count,
                "total_assignments": 0,
            },
            "suggested_actions": [
                {"label": "Course overview", "prompt": "Give me an overview of this course's health"},
                {"label": "Enrollment stats", "prompt": "What are the enrollment numbers for this course?"},
                {"label": "Accessibility audit", "prompt": "Are there any accessibility concerns in this course?"},
            ],
        }


_COACHING_PROMPTS: dict[str, str] = {
    "student": COACHING_SYSTEM_PROMPT,
    "faculty": """\
You are an AI assistant in an LMS. A faculty member just opened their course dashboard.
Write a brief, professional greeting (2-4 sentences).
Mention class size, any pending items needing attention (submissions to grade, at-risk students).
End with a concrete action they could take right now.
Do NOT use JSON. Write plain markdown only.
""",
    "advisor": """\
You are an AI assistant in an LMS. An academic advisor just opened a course view.
Write a brief, professional greeting (2-3 sentences).
Mention the number of students and any areas that might need advising attention.
End with an offer to help identify at-risk students or review degree progress.
Do NOT use JSON. Write plain markdown only.
""",
    "admin": """\
You are an AI assistant in an LMS. An administrator just opened a course view.
Write a brief, professional greeting (2-3 sentences).
Provide a high-level overview of the course health.
End with an offer to drill into enrollment, performance, or accessibility.
Do NOT use JSON. Write plain markdown only.
""",
}


class BriefGenerator:
    """Generates a course brief (card + coaching message) for any persona."""

    _gatherers: dict[str, BriefGatherer] = {
        "student": StudentBriefGatherer(),
        "faculty": FacultyBriefGatherer(),
        "advisor": AdvisorBriefGatherer(),
        "admin": AdminBriefGatherer(),
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
            # Unknown persona — still send a welcome message
            await turn_store.add_events(turn_id, [{
                "event": "final",
                "payload": {
                    "answer_markdown": "Welcome! How can I help you today?",
                    "artifacts": [],
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "wall_time_ms": 0.0,
                },
            }])
            await turn_store.update_status(turn_id, "completed")
            return

        try:
            raw_data = await gatherer.gather(person_id, course_id)
            card = gatherer.build_card(raw_data)

            chat_msg = await self._coaching_message(persona, raw_data)

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
                    "answer_markdown": "Welcome! Ask me anything to get started.",
                    "artifacts": [],
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "wall_time_ms": 0.0,
                },
            }])
            await turn_store.update_status(turn_id, "completed")

    async def _coaching_message(self, persona: str, raw_data: dict[str, Any]) -> str:
        system = _COACHING_PROMPTS.get(persona, _COACHING_PROMPTS["student"])
        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                system=system,
                messages=[{
                    "role": "user",
                    "content": f"Data:\n{json.dumps(raw_data, indent=2, default=str)}",
                }],
                max_tokens=300,
            )
            return response.content[0].text
        except Exception as exc:
            logger.warning("Coaching message generation failed: %s", exc)
            return "Welcome! I'm here to help — ask me anything to get started."
