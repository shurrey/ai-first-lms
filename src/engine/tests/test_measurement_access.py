"""§17 matrix over the AI Review and generated-items endpoints (spec.md §20 "Auth and scope").

Actors, "own" and "other" are as in test_access_matrix: "own" is Emma / the actor's course,
"other" is Noah / ENG 102. For the rollup, "own" names a program the program lead
leads and "other" one nobody leads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from engine.measurement import ActionRecord, Program
from engine.tests.auth_fakes import CS101, ENG102, MATH201
from engine.tests.measurement_fakes import InMemoryMeasurementStore
from engine.tests.test_access_matrix import ACTORS, NO, OK, OWN_COURSE

_REVIEW = {"student": (NO, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
           "program_lead": (OK, NO), "advisor": (NO, NO), "admin": (OK, OK)}
MATRIX: dict[str, dict[str, tuple[int, int]]] = {
    "measurement_course": _REVIEW,
    "measurement_export": _REVIEW,
    "measurement_rollup": {"student": (NO, NO), "faculty": (NO, NO),
                           "faculty_chen": (NO, NO), "program_lead": (OK, NO),
                           "advisor": (NO, NO), "admin": (OK, OK)},
    "ai_action": {"student": (OK, NO), "faculty": (OK, NO), "faculty_chen": (OK, NO),
                  "program_lead": (OK, NO), "advisor": (OK, NO), "admin": (OK, OK)},
}
OWN_PROGRAM = str(uuid.uuid4())
OTHER_PROGRAM = str(uuid.uuid4())


def _action_id(course: str, person: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{course}/{person}"))


@pytest.fixture(autouse=True)
def store(auth_app, auth_world) -> InMemoryMeasurementStore:
    emma, noah = auth_world.people["student"].id, auth_world.people["noah"].id
    lead = auth_world.people["program_lead"].id
    fake = InMemoryMeasurementStore(programs={
        OWN_PROGRAM: Program(OWN_PROGRAM, "Computing", frozenset({lead}),
                             frozenset({CS101.course_id})),
        OTHER_PROGRAM: Program(OTHER_PROGRAM, "Elsewhere", frozenset(),
                               frozenset({ENG102.course_id})),
    })
    for course, person in ((CS101.course_id, emma), (MATH201.course_id, emma),
                           (ENG102.course_id, noah)):
        grade = str(uuid.uuid4())
        fake.committed_grades.add(grade)
        fake.actions.append(ActionRecord(
            id=_action_id(course, person), agent="grading_assistant",
            action_type="grade_draft", output={"scores": {}},
            created_at=datetime(2026, 8, 1, tzinfo=UTC), subject_person=person,
            course_node=course, target_type="grades", target_id=grade))
    auth_app.state.measurement_store = fake
    return fake


async def _call(client, endpoint: str, *, person: str, course: str, target: str):  # noqa: ANN001
    match endpoint:
        case "measurement_course":
            return await client.get(f"/api/measurement/courses/{course}")
        case "measurement_export":
            return await client.get("/api/measurement/export", params={"course_id": course})
        case "measurement_rollup":
            params = {"program_id": OTHER_PROGRAM if target == "other" else OWN_PROGRAM}
            return await client.get("/api/measurement/rollup", params=params)
        case "ai_action":
            return await client.get(f"/api/ai-actions/{_action_id(course, person)}")
        case "ai_actions":
            return await client.get("/api/ai-actions")
    raise AssertionError(endpoint)


def _cases():
    for endpoint, row in MATRIX.items():
        for actor, (own, other) in row.items():
            yield pytest.param(endpoint, actor, "own", own, id=f"{endpoint}-{actor}-own")
            yield pytest.param(endpoint, actor, "other", other, id=f"{endpoint}-{actor}-other")


@pytest.mark.parametrize(("endpoint", "actor", "target", "expected"), list(_cases()))
async def test_measurement_matrix(authed_client, auth_world, endpoint, actor, target, expected):
    role, person_key = ACTORS[actor]
    client = await authed_client(role, person=person_key)
    if target == "own":
        person, course = auth_world.people["student"].id, OWN_COURSE[actor]
    else:
        person, course = auth_world.people["noah"].id, ENG102.course_id
    resp = await _call(client, endpoint, person=person, course=course, target=target)
    assert resp.status_code == expected, resp.text
    if expected == NO:
        assert "detail" in resp.json()


@pytest.mark.parametrize("actor", list(ACTORS))
async def test_ai_actions_log_is_open_to_every_role_and_scoped(authed_client, auth_world,
                                                                actor):
    role, person_key = ACTORS[actor]
    client = await authed_client(role, person=person_key)
    resp = await client.get("/api/ai-actions")
    assert resp.status_code == OK
    subjects = {i["subject_person_id"] for i in resp.json()["items"]}
    courses = {i["course_id"] for i in resp.json()["items"]}
    if actor == "admin":
        assert ENG102.course_id in courses
    else:
        assert ENG102.course_id not in courses
        assert auth_world.people["noah"].id not in subjects


@pytest.mark.parametrize("endpoint", [*MATRIX, "ai_actions"])
async def test_measurement_endpoints_require_sign_in(auth_client, auth_world, endpoint):
    resp = await _call(auth_client, endpoint, person=auth_world.people["student"].id,
                       course=CS101.course_id, target="own")
    assert resp.status_code == 401


PROFILE_ACTION = str(uuid.uuid4())


@pytest.mark.parametrize(("actor", "sees_profile"),
                         [("student", True), ("faculty", False), ("advisor", False),
                          ("admin", False)])
async def test_profile_text_in_generated_items_is_shown_only_to_its_subject(
        authed_client, auth_world, store, actor, sees_profile):
    emma = auth_world.people["student"].id
    store.actions.append(ActionRecord(
        id=PROFILE_ACTION, agent="learning_analyst", action_type="profile_update",
        output={"tool": "roster.update_learner_profile", "profile_md": "Prefers worked examples"},
        created_at=datetime(2026, 8, 2, tzinfo=UTC), subject_person=emma,
        course_node=CS101.course_id))
    role, person_key = ACTORS[actor]
    client = await authed_client(role, person=person_key)
    responses = [await client.get(f"/api/ai-actions/{PROFILE_ACTION}"),
                 await client.get("/api/ai-actions")]
    if actor in ("faculty", "admin"):
        responses.append(await client.get("/api/measurement/export",
                                          params={"course_id": CS101.course_id}))
    for resp in responses:
        assert resp.status_code == OK, resp.text
        assert ("Prefers worked examples" in resp.text) is sees_profile
    item = responses[0].json()
    if sees_profile:
        assert "withheld" not in item["output"]
    else:
        assert item["output"] == {"tool": "roster.update_learner_profile",
                                  "withheld": ["profile_md"]}
