"""Course brief generator — auto-summary when a session starts."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from engine.guardrails.injection import INJECTION_GUARDRAIL_INSTRUCTION, guard_prompt_data
from engine.http import make_anthropic_client

logger = logging.getLogger(__name__)

_MCP_SERVERS = {
    "roster": "http://mcp-roster:7002",
    "assessments": "http://mcp-assessments:7003",
    "content": "http://mcp-content:7001",
    "sis": "http://mcp-sis:7005",
}


@dataclass(frozen=True)
class BriefScope:
    """What the requester may see, resolved by the caller from their AuthContext.

    `course_ids` None means every course. `advisee_ids` None means no student filter.
    """

    course_ids: frozenset[str] | None = None
    advisee_ids: frozenset[str] | None = None
    advisor_count: int = 0


_UNSCOPED = BriefScope()

ALL_PAGES = frozenset(
    {"content", "gradebook", "roster", "calendar", "analytics", "courses", "mastery"}
)
# Pages listing other learners individually are kept from students (gradebook shows only
# their own row) and from program leads, who see aggregates only (spec.md §17).
_PAGES_BY_ROLE: dict[str, frozenset[str]] = {
    "student": frozenset({"content", "calendar", "mastery", "courses", "gradebook"}),
    "program_lead": frozenset({"content", "calendar", "mastery", "courses"}),
    "faculty": ALL_PAGES,
    "advisor": ALL_PAGES,
    "admin": ALL_PAGES,
}


def page_allowed(role: str, page: str) -> bool:
    """False for a known page the role may not see; unknown pages carry no data."""
    return page not in ALL_PAGES or page in _PAGES_BY_ROLE.get(role, frozenset())


def _only_advisees(students: list[dict[str, Any]], scope: BriefScope) -> list[dict[str, Any]]:
    if scope.advisee_ids is None:
        return students
    return [s for s in students if s.get("id") in scope.advisee_ids]


async def _discover_courses() -> list[dict[str, str]]:
    """Discover all courses from the SIS catalog via MCP."""
    result = await _call_mcp("sis", "sis.catalog_search", {"query": ""})
    return [
        {"id": c.get("id", ""), "title": c.get("title", "")}
        for c in result.get("courses", [])
    ]

COACHING_SYSTEM_PROMPT = """\
You are the Tutor in a mastery-based AI-native LMS. A student just opened their course.
Write a brief, warm, PROACTIVE greeting that STARTS a learning session (3-5 sentences).

You are NOT asking the student what they want to do. You are TELLING them what's next and beginning.

Based on their mastery data:
- Quickly acknowledge progress (concepts mastered, microcredentials earned)
- Identify the SPECIFIC next concept they should work on (one that's "not_started" or "emerging" with prerequisites satisfied)
- BEGIN introducing that concept — give a one-sentence preview of what they'll learn
- End with a direct lead-in: "Let's start by exploring..." or "Here's the key thing to understand about..."

Examples of GOOD openings:
- "Welcome back! You've mastered 30 concepts and earned Programming Fundamentals. Your next step is 'lists' in the Data Structures module — this is how Python stores collections of items. Let's start with what a list actually is and why you'd use one."
- "Great to see you again! You're proficient in 'for loops' — let's push that to mastery today. I'm going to give you a scenario that requires a loop with a tricky edge case."

Examples of BAD openings (do NOT do these):
- "Would you like to continue where we left off?"
- "What would you like to work on today?"
- "Here are some options for what we could study..."

Do NOT reference grades, percentages, or scores. Frame everything as mastery progress.
Do NOT use JSON. Write plain markdown only.
Do NOT use emojis excessively — one or two is fine.
"""


class BriefGatherer(Protocol):
    """Protocol for persona-specific data gathering."""

    async def gather(
        self, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]: ...

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

    async def gather(
        self, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
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
        mastery = await _call_mcp("content", "graph.mastery_map", {
            "person_id": person_id, "course_id": course_id,
        })

        return {
            "student_ctx": student_ctx,
            "evidence": evidence,
            "modules": modules,
            "mastery": mastery,
        }

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        student_ctx = raw_data.get("student_ctx", {})
        evidence_data = raw_data.get("evidence", {})
        modules_data = raw_data.get("modules", {})

        student_name = student_ctx.get("display_name", "Student")
        course_title = student_ctx.get("course_title", "")

        # Prefer student_ctx evidence (has assignment titles from node join)
        # Fall back to evidence_data if student_ctx doesn't have it
        ctx_evidence = student_ctx.get("recent_evidence", [])
        if ctx_evidence:
            evidence_list = ctx_evidence
        else:
            evidence_list = evidence_data.get("evidence", evidence_data.get("recent_evidence", []))

        assignments = []
        scores = []
        for ev in evidence_list:
            title = ev.get("title") or ev.get("kind", "Unknown")
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
            "extra": {
                "mastery_data": raw_data.get("mastery"),
            },
        }


class FacultyBriefGatherer:
    """Gathers brief data for a faculty persona."""

    async def gather(
        self, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
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
        # list_by_course returns "role" (singular, from enrollment), not "roles"
        students = [p for p in persons if p.get("role") == "student"]
        faculty = [p for p in persons if p.get("role") == "faculty"]
        all_evidence: list[dict[str, Any]] = []
        for student in students:
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
            "faculty_count": len(faculty),
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
                },
                "struggling_students": struggling[:5],
                "class_avg": class_avg,
            },
        }


class AdvisorBriefGatherer:
    """Gathers brief data for an advisor — focuses on student risk and performance.

    Only assigned students count, and "all" means courses containing one of them.
    """

    async def gather(
        self, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
        if course_id == "all":
            courses = await _discover_courses()
            if scope.course_ids is not None:
                courses = [c for c in courses if c["id"] in scope.course_ids]
            course_ids = [c["id"] for c in courses]
            course_name_map = {c["id"]: c["title"] for c in courses}
        else:
            course_ids = [course_id]
            course_name_map = {}

        # Gather data across all relevant courses
        all_students: dict[str, dict[str, Any]] = {}
        course_stats: list[dict[str, Any]] = []
        total_faculty: set[str] = set()

        for cid in course_ids:
            roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": cid})
            persons = roster.get("persons", [])
            students = _only_advisees(
                [p for p in persons if p.get("role") == "student"], scope
            )
            faculty = [p for p in persons if p.get("role") == "faculty"]
            total_faculty.update(f.get("display_name", "") for f in faculty)

            course_scores: list[float] = []
            for student in students:
                sid = student["id"]
                if sid not in all_students:
                    all_students[sid] = {"name": student.get("display_name", "Unknown"), "courses": {}, "all_scores": []}

                ev = await _call_mcp("assessments", "assessments.list_recent_evidence", {"person_id": sid, "course_id": cid})
                evidence_list = ev.get("evidence", ev.get("recent_evidence", []))
                scores = [e["score"] for e in evidence_list if e.get("score") is not None]
                avg = round(sum(scores) / len(scores), 2) if scores else 0
                all_students[sid]["courses"][cid] = {"avg": avg, "evidence_count": len(evidence_list)}
                all_students[sid]["all_scores"].extend(scores)
                course_scores.extend(scores)

            course_avg = round(sum(course_scores) / len(course_scores), 2) if course_scores else 0
            course_stats.append({
                "course_id": cid,
                "name": course_name_map.get(cid, cid[:8]),
                "students": len(students),
                "avg_score": course_avg,
            })

        return {
            "student_data": all_students,
            "course_stats": course_stats,
            "student_count": len(all_students),
            "faculty": list(total_faculty),
            "course_count": len(course_ids),
            "is_cross_course": course_id == "all",
            "persona": "advisor",
        }

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        student_data = raw_data.get("student_data", {})
        student_count = raw_data.get("student_count", 0)
        faculty = raw_data.get("faculty", [])
        course_stats = raw_data.get("course_stats", [])
        is_cross_course = raw_data.get("is_cross_course", False)

        # Categorize students by overall avg score
        at_risk = []
        low = []
        disengaged = []
        for sid, data in student_data.items():
            scores = data.get("all_scores", [])
            if not scores:
                disengaged.append({"name": data["name"], "avg": 0})
            else:
                avg = round(sum(scores) / len(scores), 2)
                if avg < 0.3:
                    at_risk.append({"name": data["name"], "avg": avg})
                elif avg < 0.5:
                    low.append({"name": data["name"], "avg": avg})
        at_risk.sort(key=lambda s: s["avg"])
        low.sort(key=lambda s: s["avg"])

        all_scores = [s for d in student_data.values() for s in d.get("all_scores", [])]
        overall_avg = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0

        return {
            "persona": "advisor",
            "student_name": "Advisor View" + (" — All Courses" if is_cross_course else ""),
            "course_title": "",
            "current_module": {"title": "", "index": 0, "total": 0},
            "assignments": [],
            "stats": {
                "avg_score": overall_avg,
                "submissions_count": student_count,
                "total_assignments": 0,
            },
            "suggested_actions": [
                {"label": "At-risk students", "prompt": "Which students across all courses need attention?"},
                {"label": "Engagement trends", "prompt": "Show me engagement trends across courses"},
                {"label": "Degree progress", "prompt": "Which students are behind on degree requirements?"},
            ],
            "extra": {
                "faculty": faculty,
                "course_stats": course_stats,
                "at_risk_students": at_risk[:5],
                "low_performing": low[:5],
                "disengaged": disengaged[:5],
                "overall_avg": overall_avg,
                "is_cross_course": is_cross_course,
                "risk_summary": {
                    "at_risk": len(at_risk),
                    "low": len(low),
                    "disengaged": len(disengaged),
                    "on_track": student_count - len(at_risk) - len(low) - len(disengaged),
                },
            },
        }


class AdminBriefGatherer:
    """Gathers brief data for an admin — platform/course health overview."""

    async def gather(
        self, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
        if course_id == "all":
            courses = await _discover_courses()
            course_ids = [c["id"] for c in courses]
            course_name_map = {c["id"]: c["title"] for c in courses}
        else:
            course_ids = [course_id]
            course_name_map = {}

        course_details: list[dict[str, Any]] = []
        all_faculty: dict[str, dict[str, Any]] = {}
        total_students = 0
        total_advisors = scope.advisor_count
        total_evidence = 0
        all_scores: list[float] = []

        for cid in course_ids:
            roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": cid})
            modules = await _call_mcp("content", "content.list_modules", {"course_id": cid})

            persons = roster.get("persons", [])
            students = [p for p in persons if p.get("role") == "student"]
            faculty = [p for p in persons if p.get("role") == "faculty"]
            module_list = modules.get("modules", [])

            total_students += len(students)

            for f in faculty:
                fid = f.get("id", "")
                if fid not in all_faculty:
                    all_faculty[fid] = {"name": f.get("display_name", ""), "id": fid, "courses": []}
                all_faculty[fid]["courses"].append(course_name_map.get(cid, cid[:8]))

            # Sample evidence from a few students per course
            import random as _random
            sample = _random.sample(students, min(5, len(students))) if students else []
            course_scores: list[float] = []
            for student in sample:
                ev = await _call_mcp("assessments", "assessments.list_recent_evidence", {"person_id": student["id"], "course_id": cid})
                evidence_list = ev.get("evidence", ev.get("recent_evidence", []))
                for e in evidence_list:
                    if e.get("score") is not None:
                        course_scores.append(e["score"])
                        all_scores.append(e["score"])
                total_evidence += len(evidence_list)

            course_avg = round(sum(course_scores) / len(course_scores), 2) if course_scores else 0
            course_details.append({
                "course_id": cid,
                "name": course_name_map.get(cid, cid[:8]),
                "students": len(students),
                "faculty": [f.get("display_name", "") for f in faculty],
                "modules": len(module_list),
                "avg_score": course_avg,
            })

        avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0

        return {
            "course_details": course_details,
            "all_faculty": list(all_faculty.values()),
            "total_students": total_students,
            "total_advisors": total_advisors,
            "total_evidence": total_evidence,
            "avg_score": avg_score,
            "course_count": len(course_ids),
            "is_cross_course": course_id == "all",
            "persona": "admin",
        }

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        course_details = raw_data.get("course_details", [])
        all_faculty = raw_data.get("all_faculty", [])
        total_students = raw_data.get("total_students", 0)
        total_advisors = raw_data.get("total_advisors", 0)
        total_evidence = raw_data.get("total_evidence", 0)
        avg_score = raw_data.get("avg_score", 0)
        is_cross_course = raw_data.get("is_cross_course", False)

        return {
            "persona": "admin",
            "student_name": "Admin View" + (" — All Courses" if is_cross_course else ""),
            "course_title": "",
            "current_module": {"title": "", "index": 0, "total": 0},
            "assignments": [],
            "stats": {
                "avg_score": avg_score,
                "submissions_count": total_students,
                "total_assignments": 0,
            },
            "suggested_actions": [
                {"label": "Platform health", "prompt": "Give me an overview of all courses' health"},
                {"label": "Enrollment stats", "prompt": "What are the enrollment numbers across all courses?"},
                {"label": "Grading pipeline", "prompt": "What's the status of the grading pipeline across all courses?"},
                {"label": "Faculty review", "prompt": "How are the instructors performing across courses?"},
            ],
            "extra": {
                "course_details": course_details,
                "faculty_details": all_faculty,
                "total_advisors": total_advisors,
                "total_evidence": total_evidence,
                "avg_score": avg_score,
                "is_cross_course": is_cross_course,
                "roster_breakdown": {
                    "total": total_students + len(all_faculty) + total_advisors,
                    "students": total_students,
                    "faculty": len(all_faculty),
                    "advisors": total_advisors,
                    "courses": len(course_details),
                },
            },
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
        self._client = make_anthropic_client()

    async def generate(
        self,
        persona: str,
        person_id: str,
        course_id: str,
        turn_id: str,
        turn_store: Any,
        page: str | None = None,
        scope: BriefScope = _UNSCOPED,
    ) -> None:
        # If a page-specific brief is requested, route to page gatherer
        if page:
            await self._generate_page_brief(
                page, persona, person_id, course_id, turn_id, turn_store, scope
            )
            return

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
            raw_data = await gatherer.gather(person_id, course_id, scope)
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

    async def _generate_page_brief(
        self, page: str, persona: str, person_id: str, course_id: str, turn_id: str, turn_store: Any,
        scope: BriefScope = _UNSCOPED,
    ) -> None:
        """Generate structured data for a specific Ultra UI page."""
        try:
            if not page_allowed(persona, page):
                data = {"error": f"The {page} page is not available to this role."}
            elif page == "content":
                data = await self._page_content(course_id)
            elif page == "gradebook":
                data = await self._page_gradebook(persona, person_id, course_id, scope)
            elif page == "roster":
                data = await self._page_roster(persona, person_id, course_id, scope)
            elif page == "calendar":
                data = await self._page_calendar(course_id)
            elif page == "analytics":
                data = await self._page_analytics(person_id, course_id, scope)
            elif page == "courses":
                data = await self._page_courses(scope)
            elif page == "mastery":
                data = await self._page_mastery(person_id, course_id)
            else:
                data = {"error": f"Unknown page: {page}"}

            events = [
                {"event": "page_data", "payload": {"page": page, "data": data}},
                {"event": "final", "payload": {
                    "answer_markdown": "", "artifacts": [],
                    "cost_usd": 0.0, "tokens": 0, "wall_time_ms": 0.0,
                }},
            ]
            await turn_store.add_events(turn_id, events)
            await turn_store.update_status(turn_id, "completed")

        except Exception as exc:
            logger.exception("Page brief generation failed for %s: %s", page, exc)
            await turn_store.add_events(turn_id, [
                {"event": "page_data", "payload": {"page": page, "data": {"error": str(exc)}}},
                {"event": "final", "payload": {
                    "answer_markdown": "", "artifacts": [],
                    "cost_usd": 0.0, "tokens": 0, "wall_time_ms": 0.0,
                }},
            ])
            await turn_store.update_status(turn_id, "completed")

    async def _page_courses(self, scope: BriefScope = _UNSCOPED) -> dict[str, Any]:
        """Course list page data, limited to the requester's courses."""
        courses = await _discover_courses()
        if scope.course_ids is not None:
            courses = [c for c in courses if c["id"] in scope.course_ids]
        result = []
        for c in courses:
            roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": c["id"]})
            persons = roster.get("persons", [])
            students = [p for p in persons if p.get("role") == "student"]
            faculty = [p for p in persons if p.get("role") == "faculty"]
            result.append({
                "id": c["id"],
                "title": c["title"],
                "studentCount": len(students),
                "instructor": faculty[0].get("display_name", "") if faculty else "",
            })
        return {"courses": result}

    async def _page_content(self, course_id: str) -> dict[str, Any]:
        """Content tab: modules + content items + faculty."""
        modules = await _call_mcp("content", "content.list_modules", {"course_id": course_id})
        roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": course_id})
        persons = roster.get("persons", [])
        faculty = [p for p in persons if p.get("role") == "faculty"]

        # Get content items for each module
        module_list = modules.get("modules", [])
        enriched_modules = []
        for mod in module_list:
            # Content items are stored with node_id = module_id
            items_result = await _call_mcp("content", "content.retrieve", {"node_id": mod["id"]})
            items = []
            if not items_result.get("error"):
                items.append({
                    "id": items_result.get("id", ""),
                    "title": items_result.get("title", ""),
                    "kind": items_result.get("kind", "document") if "kind" in items_result else "document",
                })
            enriched_modules.append({
                "id": mod["id"],
                "title": mod["title"],
                "order": mod.get("order", 0),
                "items": items,
            })

        return {
            "modules": enriched_modules,
            "faculty": [{"name": f.get("display_name", ""), "id": f.get("id", "")} for f in faculty],
        }

    async def _page_gradebook(
        self, persona: str, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
        """Gradebook page: assignments + student grades. Students see only their own data."""
        if persona == "student":
            # Student view — only their own grades
            students_to_query = [{"id": person_id, "display_name": "", "email": ""}]
            # Get student name
            student_info = await _call_mcp("roster", "roster.get_student", {"person_id": person_id})
            if not student_info.get("error"):
                students_to_query[0]["display_name"] = student_info.get("display_name", "")
                students_to_query[0]["email"] = student_info.get("email", "")
        else:
            # Faculty/admin: all students; advisor: assigned students only
            roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": course_id})
            persons = roster.get("persons", [])
            students_to_query = _only_advisees(
                [p for p in persons if p.get("role") == "student"], scope
            )

        # Get evidence for each student
        student_grades = []
        for student in students_to_query:
            ctx = await _call_mcp("roster", "roster.get_student_context", {
                "person_id": student["id"], "course_id": course_id,
            })
            evidence = ctx.get("recent_evidence", [])
            grades: dict[str, float | None] = {}
            for ev in evidence:
                title = ev.get("title", ev.get("kind", ""))
                if ev.get("score") is not None:
                    grades[title] = round(ev["score"], 2)

            all_scores = [s for s in grades.values() if s is not None]
            overall = round(sum(all_scores) / len(all_scores), 2) if all_scores else None

            student_grades.append({
                "id": student["id"],
                "name": student.get("display_name", ""),
                "email": student.get("email", ""),
                "overall": overall,
                "grades": grades,
            })

        # Get assignment list
        assignments_ctx = await _call_mcp("roster", "roster.get_student_context", {
            "person_id": students_to_query[0]["id"] if students_to_query else person_id,
            "course_id": course_id,
        })
        assignment_titles = list({
            ev.get("title", ev.get("kind", ""))
            for ev in assignments_ctx.get("recent_evidence", [])
            if ev.get("title")
        })

        return {
            "students": student_grades,
            "assignments": sorted(assignment_titles),
            "totalStudents": len(students_to_query),
        }

    async def _page_roster(
        self, persona: str, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
        """Roster page: students with scores and attributes. Students see limited view."""
        roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": course_id})
        persons = roster.get("persons", [])
        if scope.advisee_ids is not None:
            persons = [
                p for p in persons
                if p.get("role") != "student" or p.get("id") in scope.advisee_ids
            ]

        # Students see everyone but without other students' grades (grades stripped below)
        hide_other_grades = persona == "student"

        enriched = []
        for p in persons:
            if p.get("role") != "student":
                enriched.append({
                    "id": p.get("id", ""),
                    "name": p.get("display_name", ""),
                    "email": "",
                    "role": p.get("role", ""),
                    "overall": None,
                    "attributes": {},
                })
                continue

            ev = await _call_mcp("assessments", "assessments.list_recent_evidence", {
                "person_id": p["id"], "course_id": course_id,
            })
            evidence = ev.get("evidence", ev.get("recent_evidence", []))
            scores = [e["score"] for e in evidence if e.get("score") is not None]
            avg = round(sum(scores) / len(scores), 2) if scores else None

            # Get student attributes
            student = await _call_mcp("roster", "roster.get_student", {"person_id": p["id"]})

            # Students can't see other students' grades
            show_grade = not hide_other_grades or p.get("id") == person_id

            enriched.append({
                "id": p.get("id", ""),
                "name": p.get("display_name", ""),
                "email": student.get("email", "") if not hide_other_grades else "",
                "role": p.get("role", "student"),
                "overall": avg if show_grade else None,
                "attributes": student.get("attributes", {}) if show_grade else {},
            })

        return {"persons": enriched}

    async def _page_calendar(self, course_id: str) -> dict[str, Any]:
        """Calendar page: assignment due dates."""
        # Get assignments from the catalog
        modules = await _call_mcp("content", "content.list_modules", {"course_id": course_id})
        # Assignments are assessment_item nodes with due_at metadata
        # We can find them via the SIS catalog or by querying nodes directly
        # For now, use a simple approach via the content search
        result = await _call_mcp("content", "content.search", {"query": "assignment quiz exam", "course_id": course_id, "top_k": 20})
        items = result.get("results", [])
        return {
            "events": items,
            "modules": modules.get("modules", []),
        }

    async def _page_analytics(
        self, person_id: str, course_id: str, scope: BriefScope = _UNSCOPED
    ) -> dict[str, Any]:
        """Analytics page: course activity data."""
        roster = await _call_mcp("roster", "roster.list_by_course", {"course_id": course_id})
        persons = roster.get("persons", [])
        students = _only_advisees([p for p in persons if p.get("role") == "student"], scope)

        analytics = []
        for student in students:
            ev = await _call_mcp("assessments", "assessments.list_recent_evidence", {
                "person_id": student["id"], "course_id": course_id,
            })
            evidence = ev.get("evidence", ev.get("recent_evidence", []))
            scores = [e["score"] for e in evidence if e.get("score") is not None]
            avg = round(sum(scores) / len(scores), 2) if scores else None

            # Count engagement events (no score)
            engagement_count = len([e for e in evidence if e.get("score") is None])

            analytics.append({
                "id": student["id"],
                "name": student.get("display_name", ""),
                "overallGrade": avg,
                "missedDueDates": 0,  # would need assignment due dates comparison
                "hoursInCourse": round(engagement_count * 0.5, 1),  # rough proxy
                "daysSinceAccess": 0,  # would need last access tracking
            })

        return {"students": analytics}

    async def _page_mastery(self, person_id: str, course_id: str) -> dict[str, Any]:
        """Mastery map page data."""
        return await _call_mcp("content", "graph.mastery_map", {
            "person_id": person_id,
            "course_id": course_id,
        })

    async def _coaching_message(self, persona: str, raw_data: dict[str, Any]) -> str:
        system = _COACHING_PROMPTS.get(persona, _COACHING_PROMPTS["student"])
        system += INJECTION_GUARDRAIL_INSTRUCTION
        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                system=system,
                messages=[{
                    "role": "user",
                    "content": "Data:\n" + guard_prompt_data(raw_data, "brief_data",
                                                             keep_names=True),
                }],
                max_tokens=300,
            )
            return response.content[0].text
        except Exception as exc:
            logger.warning("Coaching message generation failed: %s", exc)
            return "Welcome! I'm here to help — ask me anything to get started."
