from __future__ import annotations

import json
from typing import Any

import pytest

from engine import brief
from engine.brief import AdminBriefGatherer, AdvisorBriefGatherer, BriefGenerator, BriefScope

COURSE_ID = "course-1"

ROSTER = {
    "persons": [
        {"id": "s1", "display_name": "Ada", "email": "ada@example.edu", "role": "student"},
        {"id": "s2", "display_name": "Ben", "email": "ben@example.edu", "role": "student"},
        {"id": "f1", "display_name": "Prof", "email": "prof@example.edu", "role": "faculty"},
    ]
}

CONTEXT = {
    "recent_evidence": [
        {"title": "Quiz 1", "kind": "quiz", "score": 0.8},
        {"title": "Lab 1", "kind": "lab", "score": 0.6},
    ]
}


async def _fake_call_mcp(server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool == "roster.list_by_course":
        return ROSTER
    if tool == "roster.get_student":
        person = next(p for p in ROSTER["persons"] if p["id"] == args["person_id"])
        return {"display_name": person["display_name"], "email": person["email"]}
    if tool == "roster.get_student_context":
        return CONTEXT
    if tool == "sis.catalog_search":
        return {"courses": [{"id": COURSE_ID, "title": "CS 101"},
                            {"id": "course-2", "title": "ENG 102"}]}
    if tool == "assessments.list_recent_evidence":
        return {"evidence": [{"score": 0.5}]}
    if tool == "content.list_modules":
        return {"modules": []}
    raise AssertionError(f"unexpected MCP call {server}/{tool}")


@pytest.fixture
def generator(monkeypatch: pytest.MonkeyPatch) -> BriefGenerator:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(brief, "_call_mcp", _fake_call_mcp)
    return BriefGenerator()


async def test_gradebook_student_sees_only_self(generator: BriefGenerator) -> None:
    data = await generator._page_gradebook("student", "s1", COURSE_ID)

    assert data["totalStudents"] == 1
    assert [s["id"] for s in data["students"]] == ["s1"]
    assert data["students"][0]["name"] == "Ada"
    assert data["assignments"] == ["Lab 1", "Quiz 1"]


async def test_gradebook_faculty_sees_all_students(generator: BriefGenerator) -> None:
    data = await generator._page_gradebook("faculty", "f1", COURSE_ID)

    assert data["totalStudents"] == 2
    assert [s["id"] for s in data["students"]] == ["s1", "s2"]
    assert data["students"][0]["overall"] == 0.7


ADVISOR_SCOPE = BriefScope(course_ids=frozenset({COURSE_ID}), advisee_ids=frozenset({"s1"}))


async def test_gradebook_advisor_sees_only_advisees(generator: BriefGenerator) -> None:
    data = await generator._page_gradebook("advisor", "a1", COURSE_ID, ADVISOR_SCOPE)

    assert [s["id"] for s in data["students"]] == ["s1"]


async def test_roster_page_advisor_keeps_staff_and_advisees(generator: BriefGenerator) -> None:
    data = await generator._page_roster("advisor", "a1", COURSE_ID, ADVISOR_SCOPE)

    assert [p["id"] for p in data["persons"]] == ["s1", "f1"]


async def test_courses_page_is_limited_to_scope(generator: BriefGenerator) -> None:
    data = await generator._page_courses(ADVISOR_SCOPE)

    assert [c["id"] for c in data["courses"]] == [COURSE_ID]


async def test_advisor_all_courses_brief_counts_only_advisees(generator: BriefGenerator) -> None:
    data = await AdvisorBriefGatherer().gather("a1", "all", ADVISOR_SCOPE)

    assert data["course_count"] == 1
    assert list(data["student_data"]) == ["s1"]


async def test_admin_brief_uses_scope_advisor_count(generator: BriefGenerator) -> None:
    data = await AdminBriefGatherer().gather("ad1", COURSE_ID, BriefScope(advisor_count=3))

    assert data["total_advisors"] == 3


async def test_roster_page_leaves_profile_attributes_out(
    generator: BriefGenerator, monkeypatch: pytest.MonkeyPatch
) -> None:
    attributes = {"major": "CS", "learner_profile": "# Ada", "student_insights": ["x"],
                  "goals": [{"text": "pass"}]}

    async def call_mcp(server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "roster.get_student":
            return {"email": "s@example.edu", "attributes": json.dumps(attributes)}
        return await _fake_call_mcp(server, tool, args)

    monkeypatch.setattr(brief, "_call_mcp", call_mcp)

    data = await generator._page_roster("faculty", "f1", COURSE_ID)

    students = [p for p in data["persons"] if p["role"] == "student"]
    assert [p["attributes"] for p in students] == [{"major": "CS"}, {"major": "CS"}]
