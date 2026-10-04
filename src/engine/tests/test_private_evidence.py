"""Private (practice) evidence in roster.get_student_context results reaches only its learner."""

from __future__ import annotations

import json

import pytest

from engine.guardrails.private_evidence import withhold_private_in_result
from engine.tests.auth_fakes import CS101, AuthWorld, build_auth_world
from engine.tests.test_object_scope import Rig

TOOL = "roster.get_student_context"
SHARED = {"title": "Quiz 1", "score": 0.8, "visibility": "course"}
PRACTICE = {"title": "Recursion", "score": 0.25, "visibility": "private", "source": "practice"}
UNMARKED = {"title": "Lab 1", "score": 0.6}


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


def _rig(world: AuthWorld) -> Rig:
    return Rig(world, {TOOL: {"recent_evidence": [SHARED, PRACTICE, UNMARKED],
                              "current_modules": []}})


@pytest.mark.parametrize("person,role,agent", [
    ("faculty", "faculty", "early_alert"), ("advisor", "advisor", "advising"),
    ("admin", "admin", "early_alert")])
async def test_other_viewers_get_only_shared_evidence(world, person, role, agent):
    rig = _rig(world)

    result = await rig.invoke(person, agent, TOOL, {
        "person_id": world.people["student"].id, "course_id": CS101.course_id}, role=role)

    assert result.success, result.text
    assert result.value["recent_evidence"] == [SHARED]
    assert "Recursion" not in result.text and "Lab 1" not in result.text


async def test_the_learner_gets_all_their_evidence(world):
    rig = _rig(world)

    result = await rig.invoke("student", "tutor", TOOL, {
        "person_id": world.people["student"].id, "course_id": CS101.course_id})

    assert result.success, result.text
    assert [e["title"] for e in result.value["recent_evidence"]] == [
        "Quiz 1", "Recursion", "Lab 1"]


def test_other_tools_and_non_json_results_pass_through():
    raw = json.dumps({"recent_evidence": [PRACTICE]})
    assert withhold_private_in_result("assessments.get_rubric", {"person_id": "s"}, raw,
                                      "f") == raw
    assert withhold_private_in_result(TOOL, {"person_id": "s"}, "not json", "f") == "not json"
