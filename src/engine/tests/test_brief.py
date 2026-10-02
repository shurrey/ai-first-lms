from __future__ import annotations

from typing import Any

import pytest

from engine import brief
from engine.brief import BriefGenerator

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
