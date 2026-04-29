"""Roster and session transcript API endpoints for faculty/advisor views."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/mastery/{person_id}/{course_id}")
async def get_mastery(person_id: str, course_id: str) -> dict[str, Any]:
    """Get live mastery map data for a student."""
    from engine.agents.runner import _call_mcp_tool

    raw = await _call_mcp_tool("graph.mastery_map", {
        "person_id": person_id,
        "course_id": course_id,
    })
    return json.loads(raw) if isinstance(raw, str) else raw


@router.get("/api/roster/{course_id}")
async def get_roster(course_id: str) -> dict[str, Any]:
    """Get student roster for a course with activity summary."""
    from engine.agents.runner import _call_mcp_tool

    # Get enrolled students
    roster_raw = await _call_mcp_tool("roster.list_by_course", {
        "course_id": course_id,
        "role": "student",
    })
    roster_data = json.loads(roster_raw) if isinstance(roster_raw, str) else roster_raw
    persons = roster_data.get("persons", [])

    # Enrich each student with session activity
    students = []
    for p in persons:
        # Get session count for this student in this course
        sessions_raw = await _call_mcp_tool("roster.list_student_sessions", {
            "person_id": p["id"],
            "course_id": course_id,
        })
        sessions_data = json.loads(sessions_raw) if isinstance(sessions_raw, str) else sessions_raw
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
    from engine.agents.runner import _call_mcp_tool

    args: dict[str, Any] = {"person_id": person_id}
    if course_id:
        args["course_id"] = course_id

    sessions_raw = await _call_mcp_tool("roster.list_student_sessions", args)
    sessions_data = json.loads(sessions_raw) if isinstance(sessions_raw, str) else sessions_raw

    # Get student name
    student_raw = await _call_mcp_tool("roster.get", {"person_id": person_id})
    student_data = json.loads(student_raw) if isinstance(student_raw, str) else student_raw

    return {
        "student_name": student_data.get("display_name", "Unknown"),
        "sessions": sessions_data.get("sessions", []),
    }


@router.get("/api/student/{person_id}/courses")
async def get_student_courses(person_id: str) -> dict[str, Any]:
    """Get all courses for a student with mastery summary — for advisor cross-course view."""
    from engine.agents.runner import _call_mcp_tool

    # Get all enrollments for this student
    student_raw = await _call_mcp_tool("roster.get_student", {"person_id": person_id})
    student_data = json.loads(student_raw) if isinstance(student_raw, str) else student_raw

    # Get catalog to find all courses
    catalog_raw = await _call_mcp_tool("sis.catalog_search", {"query": ""})
    catalog_data = json.loads(catalog_raw) if isinstance(catalog_raw, str) else catalog_raw
    all_courses = catalog_data.get("courses", [])

    courses = []
    for course in all_courses:
        cid = course["id"]
        # Check if student is enrolled
        roster_raw = await _call_mcp_tool("roster.list_by_course", {"course_id": cid})
        roster_data = json.loads(roster_raw) if isinstance(roster_raw, str) else roster_data
        enrolled = any(p["id"] == person_id for p in roster_data.get("persons", []))
        if not enrolled:
            continue

        # Get mastery summary
        mastery_raw = await _call_mcp_tool("graph.mastery_map", {
            "person_id": person_id,
            "course_id": cid,
        })
        mastery_data = json.loads(mastery_raw) if isinstance(mastery_raw, str) else mastery_raw
        summary = mastery_data.get("summary", {})

        # Get session count
        sessions_raw = await _call_mcp_tool("roster.list_student_sessions", {
            "person_id": person_id,
            "course_id": cid,
        })
        sessions_data = json.loads(sessions_raw) if isinstance(sessions_raw, str) else sessions_data
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
    from engine.agents.runner import _call_mcp_tool

    raw = await _call_mcp_tool("roster.get", {"person_id": person_id})
    data = json.loads(raw) if isinstance(raw, str) else raw
    attrs = data.get("attributes", {})
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    return {"insights": attrs.get("student_insights", [])}


@router.get("/api/student-goals/{person_id}")
async def get_student_goals(person_id: str) -> dict[str, Any]:
    """Get student learning goals."""
    from engine.agents.runner import _call_mcp_tool

    raw = await _call_mcp_tool("roster.get_goals", {"person_id": person_id})
    return json.loads(raw) if isinstance(raw, str) else raw


@router.get("/api/transcript/{session_id}")
async def get_transcript(session_id: str) -> dict[str, Any]:
    """Get the full conversation transcript for a session."""
    from engine.agents.runner import _call_mcp_tool

    transcript_raw = await _call_mcp_tool("roster.get_session_transcript", {
        "session_id": session_id,
    })
    return json.loads(transcript_raw) if isinstance(transcript_raw, str) else transcript_raw
