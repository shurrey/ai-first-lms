"""Roster and session transcript API endpoints for faculty/advisor views."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/mastery/{person_id}/{course_id}")
async def get_mastery(person_id: str, course_id: str) -> dict[str, Any]:
    """Get live mastery map data for a student."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("graph.mastery_map", {
        "person_id": person_id,
        "course_id": course_id,
    })


@router.get("/api/roster/{course_id}")
async def get_roster(course_id: str) -> dict[str, Any]:
    """Get student roster for a course with activity summary."""
    from engine.agents.runner import _call_mcp_json

    roster_data = await _call_mcp_json("roster.list_by_course", {
        "course_id": course_id,
        "role": "student",
    })
    persons = roster_data.get("persons", [])

    # Enrich each student with session activity
    students = []
    for p in persons:
        sessions_data = await _call_mcp_json("roster.list_student_sessions", {
            "person_id": p["id"],
            "course_id": course_id,
        })
        session_list = sessions_data.get("sessions", [])

        students.append({
            "id": p["id"],
            "name": p["display_name"],
            "session_count": len(session_list),
            "last_active": session_list[0]["created_at"] if session_list else None,
            "total_turns": sum(s["turn_count"] for s in session_list),
        })

    # Sort: students with most recent activity first
    students.sort(key=lambda s: s["last_active"] or "", reverse=True)

    return {"students": students, "total": len(students)}


@router.get("/api/student/{person_id}/sessions")
async def get_student_sessions(person_id: str, course_id: str | None = None) -> dict[str, Any]:
    """Get session list for a student, optionally filtered by course."""
    from engine.agents.runner import _call_mcp_json

    args: dict[str, Any] = {"person_id": person_id}
    if course_id:
        args["course_id"] = course_id

    sessions_data = await _call_mcp_json("roster.list_student_sessions", args)
    student_data = await _call_mcp_json("roster.get", {"person_id": person_id})

    return {
        "student_name": student_data.get("display_name", "Unknown"),
        "sessions": sessions_data.get("sessions", []),
    }


@router.get("/api/student/{person_id}/courses")
async def get_student_courses(person_id: str) -> dict[str, Any]:
    """Get all courses for a student with mastery summary — for advisor cross-course view."""
    from engine.agents.runner import _call_mcp_json

    student_data = await _call_mcp_json("roster.get_student", {"person_id": person_id})
    catalog_data = await _call_mcp_json("sis.catalog_search", {"query": ""})
    all_courses = catalog_data.get("courses", [])

    courses = []
    for course in all_courses:
        cid = course["id"]
        # Check if student is enrolled
        roster_data = await _call_mcp_json("roster.list_by_course", {"course_id": cid})
        enrolled = any(p["id"] == person_id for p in roster_data.get("persons", []))
        if not enrolled:
            continue

        mastery_data = await _call_mcp_json("graph.mastery_map", {
            "person_id": person_id,
            "course_id": cid,
        })
        summary = mastery_data.get("summary", {})

        sessions_data = await _call_mcp_json("roster.list_student_sessions", {
            "person_id": person_id,
            "course_id": cid,
        })
        session_list = sessions_data.get("sessions", [])

        courses.append({
            "course_id": cid,
            "title": course.get("title", "Unknown"),
            "mastery": summary.get("mastery", 0),
            "total_concepts": summary.get("total_concepts", 0),
            "microcredentials_earned": summary.get("microcredentials_earned", 0),
            "microcredentials_total": summary.get("microcredentials_total", 0),
            "session_count": len(session_list),
            "last_active": session_list[0]["created_at"] if session_list else None,
        })

    return {
        "student_name": student_data.get("display_name", "Unknown"),
        "courses": courses,
    }


@router.get("/api/student-insights/{person_id}")
async def get_student_insights(person_id: str) -> dict[str, Any]:
    """Get student-facing learning insights."""
    from engine.agents.runner import _call_mcp_json

    data = await _call_mcp_json("roster.get", {"person_id": person_id})
    attrs = data.get("attributes", {})
    if isinstance(attrs, str):
        import json
        attrs = json.loads(attrs)
    return {"insights": attrs.get("student_insights", [])}


@router.get("/api/student-goals/{person_id}")
async def get_student_goals(person_id: str) -> dict[str, Any]:
    """Get student learning goals."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("roster.get_goals", {"person_id": person_id})


@router.get("/api/transcript/{session_id}")
async def get_transcript(session_id: str) -> dict[str, Any]:
    """Get the full conversation transcript for a session."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("roster.get_session_transcript", {
        "session_id": session_id,
    })
