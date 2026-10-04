"""Contract tests for the formative-loop tools (spec.md §7): submit, criterion feedback,
release, improvement, weaknesses, alignment, grading status, practice and outcome subgraph."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from mcp.types import CallToolRequest

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.assessments.tools import get_tools as assessments_tools
from data_mcp.mcp_servers.content.tools import get_tools as content_tools
from data_mcp.mcp_servers.roster.tools import get_tools as roster_tools
from data_mcp.tests.contract.test_sql_injection import _NoDbPool

DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_db")

pytestmark = pytest.mark.asyncio(loop_scope="module")

LEVELS = [
    {"score": 1, "label": "Beginning", "descriptor": "Missing."},
    {"score": 2, "label": "Developing", "descriptor": "Partial."},
    {"score": 3, "label": "Proficient", "descriptor": "Clear."},
    {"score": 4, "label": "Exemplary", "descriptor": "Precise."},
]
ESSAY = (
    "Deployers should be accountable. The Dutch benefits scandal shows an agency using a risk "
    "model without review. Some argue developers know the model best."
)


class World:
    """Ids of one throwaway course; `people` maps a role name to a person id."""

    def __init__(self) -> None:
        self.ids: dict[str, uuid.UUID] = {k: uuid.uuid4() for k in (
            "course", "other_course", "assignment", "no_rubric", "rubric", "thesis", "evidence",
            "out_thesis", "out_evidence", "out_other", "concept", "module", "syllabus",
        )}
        self.people: dict[str, uuid.UUID] = {}

    def __getitem__(self, key: str) -> str:
        return str(self.ids.get(key) or self.people[key])


async def _person(conn: asyncpg.Connection, world: World, name: str, roles: list[str],
                  course: str | None = None, role: str | None = None) -> str:
    pid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        pid, roles, f"Formative {name}", f"formative-{pid}@test.edu",
    )
    if course:
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, $3)",
            pid, world.ids[course], role,
        )
    world.people[name] = pid
    return str(pid)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def servers(pool):
    return {
        "assessments": create_mcp_server("assessments", assessments_tools(pool)),
        "content": create_mcp_server("content", content_tools(pool)),
        "roster": create_mcp_server("roster", roster_tools(pool)),
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(pool):
    w = World()
    i = w.ids
    async with pool.acquire() as conn:
        for key, title in (("course", "Formative Course"), ("other_course", "Other Course")):
            await conn.execute(
                "INSERT INTO nodes (id, kind, title) VALUES ($1, 'course', $2)", i[key], title)
        course = str(i["course"])
        for key, title in (("out_thesis", "Formulate an arguable thesis"),
                           ("out_evidence", "Support claims with cited evidence from cases"),
                           ("out_other", "Format a bibliography")):
            await conn.execute(
                """INSERT INTO nodes (id, kind, title, metadata)
                   VALUES ($1, 'outcome', $2, $3)""",
                i[key], title, json.dumps({"course_id": course}),
            )
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, metadata) VALUES
               ($1, 'module', 'Evidence & Reasoning', $3), ($2, 'concept', 'Case evidence', $3)""",
            i["module"], i["concept"], json.dumps({"course_id": course}),
        )
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, description, metadata) VALUES
               ($1, 'assessment_item', 'Evidence essay', 'Use cited evidence from cases', $3),
               ($2, 'assessment_item', 'Reading quiz', 'No rubric', $4)""",
            i["assignment"], i["no_rubric"],
            json.dumps({"course_id": course, "rubric_id": str(i["rubric"]), "type": "essay"}),
            json.dumps({"course_id": course, "type": "quiz"}),
        )
        for src, dst, kind in ((i["concept"], i["out_evidence"], "aligned_with"),
                               (i["concept"], i["module"], "part_of"),
                               (i["module"], i["course"], "part_of"),
                               (i["assignment"], i["out_evidence"], "aligned_with")):
            await conn.execute(
                "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, $3)", src, dst, kind)
        await conn.execute(
            "INSERT INTO rubrics (id, title, criteria) VALUES ($1, 'Formative rubric', '[]')",
            i["rubric"],
        )
        for key, outcome in (("thesis", "out_thesis"), ("evidence", "out_evidence")):
            await conn.execute(
                """INSERT INTO rubric_criteria (id, rubric_id, key, description, levels,
                                                outcome_nodes)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                i[key], i["rubric"], key, f"The {key}", json.dumps(LEVELS), [i[outcome]],
            )
        await conn.execute(
            """INSERT INTO content_items (id, node_id, kind, title, body_md)
               VALUES ($1, $2, 'syllabus', 'Formative syllabus', 'Outcomes: thesis, evidence.')""",
            i["syllabus"], i["course"],
        )
        await _person(conn, w, "faculty", ["faculty"], "course", "faculty")
        await _person(conn, w, "other_faculty", ["faculty"], "other_course", "faculty")
        await _person(conn, w, "admin", ["admin"])
        await _person(conn, w, "lead", ["faculty", "program_lead"])
        await _person(conn, w, "advisor", ["advisor"])
        await _person(conn, w, "outsider", ["student"], "other_course", "student")
    yield w
    async with pool.acquire() as conn:
        people = list(w.people.values())
        await conn.execute("DELETE FROM advisor_assignments WHERE advisor_id = ANY($1::uuid[])",
                           people)
        subs = [r["id"] for r in await conn.fetch(
            "SELECT id FROM submissions WHERE person_id = ANY($1::uuid[])", people)]
        await conn.execute("DELETE FROM grades WHERE submission_id = ANY($1::uuid[])", subs)
        await conn.execute(
            "UPDATE submissions SET parent_id = NULL WHERE id = ANY($1::uuid[])", subs)
        await conn.execute("DELETE FROM submissions WHERE id = ANY($1::uuid[])", subs)
        await conn.execute(
            "DELETE FROM ai_actions WHERE course_node = $1 OR subject_person = ANY($2::uuid[])",
            i["course"], people,
        )
        await conn.execute(
            """DELETE FROM questions WHERE bank_id IN
               (SELECT id FROM question_banks WHERE course_node = $1)""", i["course"])
        await conn.execute("DELETE FROM question_banks WHERE course_node = $1", i["course"])
        await conn.execute("DELETE FROM content_items WHERE node_id = $1", i["course"])
        await conn.execute("DELETE FROM rubrics WHERE id = $1", i["rubric"])
        await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])", [
            i[k] for k in ("assignment", "no_rubric", "out_thesis", "out_evidence", "out_other",
                           "concept", "module", "course", "other_course")])
        await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])", people)


async def _call(server, name: str, args: dict) -> dict:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(method="tools/call", params={"name": name, "arguments": args})
    )
    return json.loads(result.root.content[0].text)


def _no_db_handler(tools, name: str):
    """The handler bound to a pool that fails if touched: validation must come first."""
    return {t.name: t.handler for t in tools(_NoDbPool())}[name]


async def _student(pool, world: World, name: str | None = None) -> str:
    async with pool.acquire() as conn:
        return await _person(conn, world, name or f"s-{uuid.uuid4().hex[:8]}", ["student"],
                             "course", "student")


def _feedback(world: World, thesis: int, evidence: int) -> list[dict[str, Any]]:
    return [
        {"criterion_id": world["thesis"], "ai_score": thesis, "ai_rationale": "Thesis is stated.",
         "ai_evidence_spans": [{"quote": "Deployers should be accountable."}],
         "next_step": "Make the position more precise."},
        {"criterion_id": world["evidence"], "ai_score": evidence,
         "ai_rationale": "One case only.",
         "ai_evidence_spans": [{"quote": "The Dutch benefits scandal", "start": 33, "end": 59}],
         "next_step": "Add a second, specific case."},
    ]


async def _draft(servers, world: World, student: str, parent: str | None = None,
                 status: str = "draft") -> dict:
    args = {"person_id": student, "assignment_node": world["assignment"], "body_md": ESSAY,
            "status": status}
    if parent:
        args["parent_id"] = parent
    return await _call(servers["assessments"], "assessments.submit", args)


async def _scored(servers, world: World, student: str, thesis: int, evidence: int,
                  parent: str | None = None, release: bool = True) -> str:
    sub = await _draft(servers, world, student, parent)
    saved = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": sub["submission_id"], "criteria": _feedback(world, thesis, evidence)})
    assert saved["saved"] == 2, saved
    if release:
        released = await _call(servers["assessments"], "assessments.release_feedback",
                               {"submission_id": sub["submission_id"]})
        assert released["released"] == 2, released
    return sub["submission_id"]


async def _history(servers, world: World, student: str, requester: str | None) -> list[dict]:
    args = {"person_id": student, "assignment_node": world["assignment"]}
    if requester:
        args["requester_id"] = requester
    result = await _call(servers["assessments"], "assessments.list_submission_history", args)
    return result["submissions"]


# ── assessments.submit ───────────────────────────────────────────────────────────────

async def test_submit_draft_then_revision_increments_version(servers, world, pool) -> None:
    student = await _student(pool, world)
    first = await _draft(servers, world, student)
    assert (first["version"], first["status"], first["parent_id"]) == (1, "draft", None)
    assert first["course_id"] == world["course"]
    second = await _draft(servers, world, student, parent=first["submission_id"])
    assert (second["version"], second["parent_id"]) == (2, first["submission_id"])
    final = await _draft(servers, world, student, parent=second["submission_id"], status="final")
    assert (final["version"], final["status"]) == (3, "final")


async def test_submit_conflicts(servers, world, pool) -> None:
    student = await _student(pool, world)
    first = await _draft(servers, world, student)
    no_parent = await _draft(servers, world, student)
    assert no_parent["code"] == "conflict"
    second = await _draft(servers, world, student, parent=first["submission_id"])
    stale = await _draft(servers, world, student, parent=first["submission_id"])
    assert stale["code"] == "conflict"
    await _draft(servers, world, student, parent=second["submission_id"], status="final")
    after_final = await _draft(servers, world, student, parent=second["submission_id"])
    assert after_final["code"] == "conflict"


async def test_submit_rejects_another_learners_parent(servers, world, pool) -> None:
    owner = await _student(pool, world)
    other = await _student(pool, world)
    first = await _draft(servers, world, owner)
    await _draft(servers, world, other)
    result = await _draft(servers, world, other, parent=first["submission_id"])
    assert result["code"] == "validation_error"


async def test_submit_requires_enrollment_and_a_real_assignment(servers, world) -> None:
    outsider = await _draft(servers, world, world["outsider"])
    assert outsider["code"] == "forbidden"
    missing = await _call(servers["assessments"], "assessments.submit", {
        "person_id": world["outsider"], "assignment_node": str(uuid.uuid4()),
        "body_md": "x", "status": "draft"})
    assert missing["code"] == "not_found"


@pytest.mark.parametrize("override", [
    {"status": "published"},
    {"body_md": "   "},
    {"body_md": 42},
    {"assignment_node": "x' OR '1'='1"},
    {"person_id": "level; DROP TABLE nodes"},
    {"parent_id": "not-a-uuid"},
    {"attachments": "not-a-list"},
    {"attachments": [1, 2]},
])
async def test_submit_validates_before_touching_the_database(override) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.submit")
    args = {"person_id": str(uuid.uuid4()), "assignment_node": str(uuid.uuid4()),
            "body_md": "essay", "status": "draft", **override}
    assert (await handler(args))["code"] == "validation_error"


# ── assessments.save_criterion_feedback ──────────────────────────────────────────────

async def test_save_feedback_writes_ai_columns_only_and_records_the_action(
    servers, world, pool,
) -> None:
    student = await _student(pool, world)
    sub = await _draft(servers, world, student)
    saved = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": sub["submission_id"], "criteria": _feedback(world, 3, 2)})
    assert saved["saved"] == 2 and len(saved["criterion_score_ids"]) == 2
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ai_score, final_score, released_at, ai_action_id, ai_evidence_spans
               FROM criterion_scores WHERE submission_id = $1""",
            uuid.UUID(sub["submission_id"]),
        )
        action = await conn.fetchrow(
            "SELECT agent, action_type, subject_person, course_node, output FROM ai_actions "
            "WHERE id = $1", uuid.UUID(saved["ai_action_id"]),
        )
    assert sorted(r["ai_score"] for r in rows) == [2, 3]
    assert all(r["final_score"] is None and r["released_at"] is None for r in rows)
    assert {str(r["ai_action_id"]) for r in rows} == {saved["ai_action_id"]}
    assert (action["agent"], action["action_type"]) == ("feedback", "criterion_feedback")
    assert (str(action["subject_person"]), str(action["course_node"])) == (
        student, world["course"])
    assert {c["next_step"] for c in json.loads(action["output"])["criteria"]} == {
        "Make the position more precise.", "Add a second, specific case."}


async def test_unreleased_draft_feedback_is_masked_from_all_but_course_faculty(
    servers, world, pool,
) -> None:
    student = await _student(pool, world)
    await _scored(servers, world, student, 3, 2, release=False)
    mine = (await _history(servers, world, student, student))[0]
    assert mine["feedback_status"] == "awaiting_release"
    assert all(c["ai_score"] is None and c["ai_rationale"] is None and c["next_step"] is None
               and c["ai_evidence_spans"] == [] for c in mine["criteria"])
    staff = (await _history(servers, world, student, world["faculty"]))[0]
    assert {c["key"]: c["ai_score"] for c in staff["criteria"]} == {"thesis": 3, "evidence": 2}
    other_course = (await _history(servers, world, student, world["other_faculty"]))[0]
    assert all(c["ai_score"] is None for c in other_course["criteria"])
    admin = (await _history(servers, world, student, world["admin"]))[0]
    assert all(c["ai_score"] is None and c["ai_evidence_spans"] == [] and c["ai_rationale"] is None
               for c in admin["criteria"])


@pytest.mark.parametrize("change,message", [
    ({"ai_score": 7}, "not a level"),
    ({"ai_evidence_spans": [{"quote": "a sentence that is not in the essay"}]}, "verbatim"),
    ({"ai_evidence_spans": [{"quote": "Deployers", "start": 3, "end": 12}]}, "start/end"),
    ({"next_step": ""}, "next_step"),
    ({"criterion_id": str(uuid.uuid4())}, "not on this assignment's rubric"),
])
async def test_save_feedback_rejects_invalid_criteria(servers, world, pool, change,
                                                      message) -> None:
    student = await _student(pool, world)
    sub = await _draft(servers, world, student)
    criteria = _feedback(world, 3, 2)
    criteria[0] = {**criteria[0], **change}
    result = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": sub["submission_id"], "criteria": criteria})
    assert result["code"] == "validation_error"
    assert message in result["error"]


async def test_save_feedback_refuses_to_overwrite_released_feedback(servers, world,
                                                                    pool) -> None:
    student = await _student(pool, world)
    sub_id = await _scored(servers, world, student, 3, 2)
    again = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": sub_id, "criteria": _feedback(world, 4, 4)})
    assert again["code"] == "conflict"


async def test_resaving_other_criteria_keeps_a_suppressed_one_hidden(servers, world,
                                                                     pool) -> None:
    student = await _student(pool, world)
    sub_id = await _scored(servers, world, student, 3, 2, release=False)
    await _call(servers["assessments"], "assessments.release_feedback", {
        "submission_id": sub_id, "decision": "suppress", "reviewer_id": world["faculty"],
        "criterion_ids": [world["evidence"]]})
    resaved = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": sub_id, "criteria": _feedback(world, 4, 2)[:1]})
    assert resaved["saved"] == 1, resaved
    released = await _call(servers["assessments"], "assessments.release_feedback",
                           {"submission_id": sub_id})
    assert released["released"] == 1
    mine = (await _history(servers, world, student, student))[0]
    assert {c["key"]: c["ai_score"] for c in mine["criteria"]} == {"thesis": 4,
                                                                   "evidence": None}


async def test_save_feedback_refuses_to_overwrite_suppressed_feedback(servers, world,
                                                                      pool) -> None:
    student = await _student(pool, world)
    sub_id = await _scored(servers, world, student, 3, 2, release=False)
    await _call(servers["assessments"], "assessments.release_feedback", {
        "submission_id": sub_id, "decision": "suppress", "reviewer_id": world["faculty"],
        "criterion_ids": [world["evidence"]]})
    again = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": sub_id, "criteria": _feedback(world, 3, 3)})
    assert again["code"] == "conflict" and "evidence" in again["error"]
    mine = (await _history(servers, world, student, world["faculty"]))[0]
    assert {c["key"]: c["ai_score"] for c in mine["criteria"]}["evidence"] == 2


async def _links_for(pool, submission_id: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT delta FROM outcome_links WHERE delta->>'submission_id' = $1
               ORDER BY delta->>'criterion'""",
            submission_id,
        )
    return [json.loads(r["delta"]) for r in rows]


async def test_revision_feedback_is_not_linked_until_released(servers, world, pool) -> None:
    student = await _student(pool, world)
    first = await _scored(servers, world, student, 3, 2)
    second = await _scored(servers, world, student, 3, 3, parent=first, release=False)
    assert await _links_for(pool, second) == []
    released = await _call(servers["assessments"], "assessments.release_feedback",
                           {"submission_id": second})
    assert released["outcome_links"] == 2
    deltas = {d["criterion"]: d for d in await _links_for(pool, second)}
    assert (deltas["evidence"]["before"], deltas["evidence"]["after"],
            deltas["evidence"]["delta"]) == (2, 3, 1)
    assert deltas["evidence"]["parent_id"] == first


async def test_releasing_the_parent_after_the_revision_links_the_revision(servers, world,
                                                                         pool) -> None:
    student = await _student(pool, world)
    first = await _scored(servers, world, student, 3, 2, release=False)
    second = await _scored(servers, world, student, 3, 3, parent=first)
    assert await _links_for(pool, second) == []
    released = await _call(servers["assessments"], "assessments.release_feedback",
                           {"submission_id": first})
    assert released["outcome_links"] == 2
    deltas = {d["criterion"]: (d["before"], d["after"], d["parent_id"])
              for d in await _links_for(pool, second)}
    assert deltas == {"evidence": (2, 3, first), "thesis": (3, 3, first)}


async def test_resaving_revision_feedback_does_not_duplicate_links(servers, world,
                                                                   pool) -> None:
    student = await _student(pool, world)
    first = await _scored(servers, world, student, 3, 2)
    second = await _draft(servers, world, student, parent=first)
    for evidence in (2, 3):
        await _call(servers["assessments"], "assessments.save_criterion_feedback", {
            "submission_id": second["submission_id"],
            "criteria": _feedback(world, 3, evidence)})
    await _call(servers["assessments"], "assessments.release_feedback",
                {"submission_id": second["submission_id"]})
    links = await _links_for(pool, second["submission_id"])
    assert [(d["criterion"], d["after"]) for d in links] == [("evidence", 3), ("thesis", 3)]


async def test_release_links_the_instructors_edited_score(servers, world, pool) -> None:
    student = await _student(pool, world)
    first = await _scored(servers, world, student, 3, 2)
    second = await _scored(servers, world, student, 3, 4, parent=first, release=False)
    await _call(servers["assessments"], "assessments.release_feedback", {
        "submission_id": second, "reviewer_id": world["faculty"],
        "criterion_ids": [world["evidence"]],
        "edits": [{"criterion_id": world["evidence"], "ai_score": 3}]})
    assert [(d["criterion"], d["after"]) for d in await _links_for(pool, second)] == [
        ("evidence", 3)]


async def test_a_parent_score_the_learner_never_saw_is_not_linked(servers, world,
                                                                  pool) -> None:
    student = await _student(pool, world)
    first = await _scored(servers, world, student, 3, 2, release=False)
    await _call(servers["assessments"], "assessments.release_feedback", {
        "submission_id": first, "decision": "suppress", "reviewer_id": world["faculty"],
        "criterion_ids": [world["evidence"]]})
    await _call(servers["assessments"], "assessments.release_feedback",
                {"submission_id": first})
    second = await _scored(servers, world, student, 3, 3, parent=first)
    assert [d["criterion"] for d in await _links_for(pool, second)] == ["thesis"]


async def test_committing_a_final_links_its_final_scores(servers, world, pool) -> None:
    student = await _student(pool, world)
    first = await _scored(servers, world, student, 3, 2)
    final = await _draft(servers, world, student, parent=first, status="final")
    drafted = await _call(servers["assessments"], "assessments.draft_grade", {
        "submission_id": final["submission_id"], "rubric_id": str(world.ids["rubric"]),
        "scores": {"thesis": 4, "evidence": 4}, "feedback": {},
        "graded_by": world["faculty"]})
    assert await _links_for(pool, final["submission_id"]) == []
    await _call(servers["assessments"], "assessments.commit_grade", {
        "grade_id": drafted["grade_id"], "final_scores": {"thesis": 3, "evidence": 3},
        "holistic_md": "Stronger evidence."})
    links = await _links_for(pool, final["submission_id"])
    assert [(d["criterion"], d["before"], d["after"]) for d in links] == [
        ("evidence", 2, 3), ("thesis", 3, 3)]


# ── assessments.release_feedback ─────────────────────────────────────────────────────

async def test_release_with_edits_records_diffs_and_shows_edited_feedback(
    servers, world, pool,
) -> None:
    student = await _student(pool, world)
    sub_id = await _scored(servers, world, student, 3, 2, release=False)
    result = await _call(servers["assessments"], "assessments.release_feedback", {
        "submission_id": sub_id, "reviewer_id": world["faculty"],
        "edits": [{"criterion_id": world["evidence"], "ai_score": 1,
                   "next_step": "Name a second case and say why it matters."}],
    })
    assert (result["decision"], result["released"], result["edited"]) == ("release", 2, 1)
    async with pool.acquire() as conn:
        decisions = await conn.fetch(
            """SELECT hd.decision, hd.diff, hd.decided_by FROM human_decisions hd
               JOIN criterion_scores cs ON cs.ai_action_id = hd.ai_action_id
               WHERE cs.submission_id = $1 AND hd.diff->>'criterion_id' = cs.criterion_id::text
               ORDER BY hd.decision""",
            uuid.UUID(sub_id),
        )
    assert [d["decision"] for d in decisions] == ["accepted", "edited"]
    assert all(str(d["decided_by"]) == world["faculty"] for d in decisions)
    diff = json.loads(decisions[1]["diff"])
    assert diff["criteria"]["evidence"] == {"before": 2, "after": 1, "delta": -1}
    assert diff["fields"]["next_step"]["before"] == "Add a second, specific case."
    mine = (await _history(servers, world, student, student))[0]
    evidence = next(c for c in mine["criteria"] if c["key"] == "evidence")
    assert mine["feedback_status"] == "released"
    assert (evidence["ai_score"], evidence["level_label"]) == (1, "Beginning")
    assert evidence["next_step"] == "Name a second case and say why it matters."
    assert evidence["ai_evidence_spans"][0]["quote"] == "The Dutch benefits scandal"
    again = await _call(servers["assessments"], "assessments.release_feedback",
                        {"submission_id": sub_id})
    assert again["code"] == "conflict"


async def test_suppressed_feedback_never_reaches_the_student(servers, world, pool) -> None:
    student = await _student(pool, world)
    sub_id = await _scored(servers, world, student, 3, 2, release=False)
    result = await _call(servers["assessments"], "assessments.release_feedback", {
        "submission_id": sub_id, "decision": "suppress", "reviewer_id": world["faculty"],
        "reason": "Off-target feedback"})
    assert (result["suppressed"], result["released"]) == (2, 0)
    mine = (await _history(servers, world, student, student))[0]
    assert mine["feedback_status"] == "suppressed"
    assert all(c["ai_score"] is None for c in mine["criteria"])
    again = await _call(servers["assessments"], "assessments.release_feedback",
                        {"submission_id": sub_id})
    assert again["code"] == "conflict"


@pytest.mark.parametrize("args", [
    {"decision": "publish"},
    {"decision": "suppress"},
    {"edits": [{"criterion_id": str(uuid.uuid4()), "ai_score": 2}]},
    {"decision": "suppress", "reviewer_id": str(uuid.uuid4()),
     "edits": [{"criterion_id": str(uuid.uuid4()), "ai_score": 2}]},
    {"criterion_ids": []},
    {"criterion_ids": ["x' OR '1'='1"]},
    {"reviewer_id": "level; DROP TABLE nodes"},
])
async def test_release_rejects_invalid_arguments(args) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.release_feedback")
    result = await handler({"submission_id": str(uuid.uuid4()), **args})
    assert result["code"] == "validation_error"


async def test_only_the_submitter_or_course_faculty_save_feedback(servers, world, pool) -> None:
    student = await _student(pool, world)
    sub = await _draft(servers, world, student)
    for requester, expected in ((world["outsider"], "forbidden"),
                                (world["other_faculty"], "forbidden"),
                                (student, None), (world["faculty"], None)):
        result = await _call(servers["assessments"], "assessments.save_criterion_feedback", {
            "submission_id": sub["submission_id"], "criteria": _feedback(world, 3, 2),
            "requester_id": requester})
        assert result.get("code") == expected, result


async def test_only_course_faculty_release_feedback(servers, world, pool) -> None:
    student = await _student(pool, world)
    sub_id = await _scored(servers, world, student, 3, 2, release=False)
    for reviewer in (world["other_faculty"], world["admin"], student):
        result = await _call(servers["assessments"], "assessments.release_feedback", {
            "submission_id": sub_id, "reviewer_id": reviewer})
        assert result["code"] == "forbidden"


async def test_release_never_applies_to_a_final_version(servers, world, pool) -> None:
    student = await _student(pool, world)
    final = await _draft(servers, world, student, status="final")
    await _call(servers["assessments"], "assessments.save_criterion_feedback", {
        "submission_id": final["submission_id"], "criteria": _feedback(world, 3, 2)})
    result = await _call(servers["assessments"], "assessments.release_feedback",
                         {"submission_id": final["submission_id"]})
    assert result["code"] == "conflict"
    staff = (await _history(servers, world, student, world["faculty"]))[0]
    assert staff["feedback_status"] == "none"


async def test_release_of_an_unknown_submission_is_not_found(servers) -> None:
    result = await _call(servers["assessments"], "assessments.release_feedback",
                         {"submission_id": str(uuid.uuid4())})
    assert result["code"] == "not_found"


# ── assessments.draft_grade / assessments.commit_grade on §7.2 criteria ─────────────

async def _drafted_final(servers, world: World, pool) -> tuple[str, str]:
    student = await _student(pool, world)
    final = await _draft(servers, world, student, status="final")
    drafted = await _call(servers["assessments"], "assessments.draft_grade", {
        "submission_id": final["submission_id"], "rubric_id": str(world.ids["rubric"]),
        "scores": {"thesis": 3, "Evidence": 2},
        "feedback": {"thesis": "Clear position.", "evidence": "One case only."},
        "graded_by": world["faculty"]})
    return final["submission_id"], drafted["grade_id"]


async def _criterion_rows(pool, submission_id: str) -> dict[str, tuple]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT rc.key, cs.ai_score, cs.ai_rationale, cs.final_score, cs.released_at
               FROM criterion_scores cs JOIN rubric_criteria rc ON rc.id = cs.criterion_id
               WHERE cs.submission_id = $1""",
            uuid.UUID(submission_id),
        )
    return {r["key"]: (r["ai_score"], r["ai_rationale"], r["final_score"], r["released_at"])
            for r in rows}


async def test_draft_grade_on_a_final_writes_ai_scores_only(servers, world, pool) -> None:
    sub, _ = await _drafted_final(servers, world, pool)
    assert await _criterion_rows(pool, sub) == {
        "thesis": (3, "Clear position.", None, None),
        "evidence": (2, "One case only.", None, None),
    }


async def test_draft_grade_on_a_draft_leaves_criterion_scores_alone(servers, world,
                                                                    pool) -> None:
    student = await _student(pool, world)
    draft = await _draft(servers, world, student)
    await _call(servers["assessments"], "assessments.draft_grade", {
        "submission_id": draft["submission_id"], "scores": {"thesis": 4},
        "feedback": {}, "graded_by": world["faculty"]})
    assert await _criterion_rows(pool, draft["submission_id"]) == {}


async def test_commit_grade_writes_the_instructors_scores_and_comment(servers, world,
                                                                     pool) -> None:
    sub, grade_id = await _drafted_final(servers, world, pool)
    result = await _call(servers["assessments"], "assessments.commit_grade", {
        "grade_id": grade_id, "final_scores": {"Thesis": 3, "evidence": 3},
        "holistic_md": "The second case carried the argument.",
        "feedback": {"evidence": "Two cases, both cited."}})
    assert result["committed"] is True, result
    rows = await _criterion_rows(pool, sub)
    assert {k: v[2] for k, v in rows.items()} == {"thesis": 3, "evidence": 3}
    assert rows["evidence"][0] == 2
    async with pool.acquire() as conn:
        grade = await conn.fetchrow(
            "SELECT scores, holistic_md, feedback, is_draft FROM grades WHERE id = $1",
            uuid.UUID(grade_id))
    assert json.loads(grade["scores"]) == {"thesis": 3, "evidence": 3}
    assert grade["holistic_md"] == "The second case carried the argument."
    assert json.loads(grade["feedback"]) == {"thesis": "Clear position.",
                                             "evidence": "Two cases, both cited."}
    assert grade["is_draft"] is False


@pytest.mark.parametrize("override,message", [
    ({"final_scores": {}}, "final_scores"),
    ({"final_scores": {"thesis": 3}}, "missing evidence"),
    ({"final_scores": {"thesis": 3, "evidence": 9}}, "not a level"),
    ({"final_scores": {"thesis": 3, "evidence": 2.5}}, "whole number"),
    ({"final_scores": {"thesis": 3, "evidence": 3, "voice": 2}}, "not a criterion"),
    ({"holistic_md": "   "}, "holistic_md"),
    ({"feedback": {"evidence": 3}}, "feedback"),
])
async def test_commit_grade_refuses_incomplete_instructor_inputs(servers, world, pool,
                                                                 override, message) -> None:
    _, grade_id = await _drafted_final(servers, world, pool)
    args = {"grade_id": grade_id, "final_scores": {"thesis": 3, "evidence": 3},
            "holistic_md": "Done.", **override}
    result = await _call(servers["assessments"], "assessments.commit_grade", args)
    assert result["code"] == "validation_error" and message in result["error"], result
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT is_draft FROM grades WHERE id = $1",
                                   uuid.UUID(grade_id)) is True


# ── assessments.reject_credential ────────────────────────────────────────────────────

async def test_reject_credential_closes_the_pending_row_once(servers, world, pool) -> None:
    student = await _student(pool, world)
    badge, pending = uuid.uuid4(), uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO nodes (id, kind, title) VALUES ($1, 'microcredential', 'Badge')", badge)
        await conn.execute(
            """INSERT INTO pending_credentials (id, person_id, microcredential_id, course_id)
               VALUES ($1, $2, $3, $4)""",
            pending, uuid.UUID(student), badge, world.ids["course"])
    try:
        args = {"pending_id": str(pending), "reviewer_id": world["faculty"],
                "reason": "Mastery came from one session only."}
        result = await _call(servers["assessments"], "assessments.reject_credential", args)
        assert result == {"rejected": True, "pending_id": str(pending)}
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, reviewed_by FROM pending_credentials WHERE id = $1", pending)
            issued = await conn.fetchval(
                "SELECT count(*) FROM issued_credentials WHERE microcredential_id = $1", badge)
        assert (row["status"], str(row["reviewed_by"]), issued) == (
            "rejected", world["faculty"], 0)
        again = await _call(servers["assessments"], "assessments.reject_credential", args)
        assert again["code"] == "conflict"
        missing = await _call(servers["assessments"], "assessments.reject_credential",
                              {**args, "pending_id": str(uuid.uuid4())})
        assert missing["code"] == "not_found"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM pending_credentials WHERE id = $1", pending)
            await conn.execute("DELETE FROM nodes WHERE id = $1", badge)


@pytest.mark.parametrize("override", [
    {"pending_id": "x' OR '1'='1"}, {"reviewer_id": None}, {"reason": ""},
])
async def test_reject_credential_validates_before_touching_the_database(override) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.reject_credential")
    args = {"pending_id": str(uuid.uuid4()), "reviewer_id": str(uuid.uuid4()), **override}
    assert (await handler(args))["code"] == "validation_error"


# ── assessments.get_improvement / assessments.weaknesses ────────────────────────────

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def improvement(servers, world, pool):
    """Three learners: improving (evidence 2 -> 3), plateaued (2 -> 2) and regressed (3 -> 2),
    plus one whose two below-target drafts were never released."""
    names = {}
    for name, first, second in (("improver", 2, 3), ("plateau", 2, 2), ("regressor", 3, 2)):
        student = await _student(pool, world, name)
        sub = await _scored(servers, world, student, 3, first)
        await _scored(servers, world, student, 3, second, parent=sub)
        names[name] = student
    names["hidden"] = await _student(pool, world, "hidden")
    hidden = await _scored(servers, world, names["hidden"], 1, 1, release=False)
    await _scored(servers, world, names["hidden"], 1, 1, parent=hidden, release=False)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO advisor_assignments (advisor_id, student_id) VALUES ($1, $2)",
            world.people["advisor"], uuid.UUID(names["plateau"]),
        )
    return names


def _flags(result: dict, key: str = "evidence") -> dict[str, str | None]:
    return {
        s["display_name"].removeprefix("Formative "): next(
            t["flag"] for t in s["trajectories"] if t["key"] == key)
        for s in result["students"] if any(t["key"] == key for t in s["trajectories"])
    }


async def test_improvement_faculty_sees_flags_per_student(servers, world, improvement) -> None:
    result = await _call(servers["assessments"], "assessments.get_improvement", {
        "course_id": world["course"], "requester_id": world["faculty"]})
    assert result["view"] == "detail"
    flags = _flags(result)
    assert (flags["improver"], flags["plateau"], flags["regressor"]) == (
        "ready_for_summative", "plateaued", "regressed")
    assert "hidden" not in flags
    improver = next(s for s in result["students"] if s["student_id"] == improvement["improver"])
    evidence = next(t for t in improver["trajectories"] if t["key"] == "evidence")
    assert [p["score"] for p in evidence["points"]] == [2, 3]
    assert evidence["delta"] == 1
    assert {c["key"]: c["target_score"] for c in result["criteria"]} == {
        "evidence": 3, "thesis": 3}


async def test_improvement_student_sees_only_self(servers, world, improvement) -> None:
    mine = await _call(servers["assessments"], "assessments.get_improvement", {
        "course_id": world["course"], "requester_id": improvement["plateau"]})
    assert mine["view"] == "self"
    assert [s["student_id"] for s in mine["students"]] == [improvement["plateau"]]
    assert "aggregate" not in mine
    other = await _call(servers["assessments"], "assessments.get_improvement", {
        "course_id": world["course"], "requester_id": improvement["plateau"],
        "student_id": improvement["improver"]})
    assert other["code"] == "forbidden"


@pytest.mark.parametrize("who", ["admin", "lead"])
async def test_improvement_admin_and_program_lead_get_aggregates_only(
    servers, world, improvement, who,
) -> None:
    result = await _call(servers["assessments"], "assessments.get_improvement", {
        "course_id": world["course"], "requester_id": world[who]})
    assert result["view"] == "aggregate" and "students" not in result
    evidence = world["evidence"]
    counts = {d["flag"]: d["count"] for d in result["distribution"]
              if d["criterion_id"] == evidence}
    assert counts["plateaued"] >= 1 and counts["regressed"] >= 1


async def test_improvement_advisor_summary_covers_assigned_students_only(
    servers, world, improvement,
) -> None:
    result = await _call(servers["assessments"], "assessments.get_improvement", {
        "course_id": world["course"], "requester_id": world["advisor"]})
    assert result["view"] == "summary" and "students" not in result
    evidence = next(a for a in result["aggregate"] if a["criterion_id"] == world["evidence"])
    assert (evidence["n_students"], evidence["flag_counts"]) == (1, {"plateaued": 1})


async def test_improvement_refuses_unrelated_or_missing_requesters(servers, world) -> None:
    unrelated = await _call(servers["assessments"], "assessments.get_improvement", {
        "course_id": world["course"], "requester_id": world["outsider"]})
    assert unrelated["code"] == "forbidden"
    missing = await _no_db_handler(assessments_tools, "assessments.get_improvement")({
        "course_id": world["course"]})
    assert missing["code"] == "validation_error"


async def test_weaknesses_follow_the_two_of_last_n_rule(servers, world, improvement) -> None:
    plateau = await _call(servers["assessments"], "assessments.weaknesses", {
        "student_id": improvement["plateau"], "course_id": world["course"]})
    assert [w["key"] for w in plateau["weaknesses"]] == ["evidence"]
    weak = plateau["weaknesses"][0]
    assert (weak["below_target_count"], weak["window"], weak["last_scores"]) == (2, 3, [2, 2])
    assert weak["outcome_nodes"] == [world["out_evidence"]]
    assert weak["criterion_id"] == world["evidence"]
    improver = await _call(servers["assessments"], "assessments.weaknesses", {
        "student_id": improvement["improver"], "course_id": world["course"]})
    assert improver["weaknesses"] == []


async def test_weaknesses_ignore_two_unreleased_below_target_drafts(servers, world,
                                                                    improvement) -> None:
    hidden = await _call(servers["assessments"], "assessments.weaknesses", {
        "student_id": improvement["hidden"], "course_id": world["course"]})
    assert hidden["weaknesses"] == []


@pytest.mark.parametrize("args", [
    {"window": 1}, {"window": 11}, {"window": "3"}, {"window": True},
    {"student_id": "x' OR '1'='1"}, {"course_id": None},
])
async def test_weaknesses_rejects_bad_arguments(args) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.weaknesses")
    result = await handler({"student_id": str(uuid.uuid4()), "course_id": str(uuid.uuid4()),
                            **args})
    assert result["code"] == "validation_error" and result["weaknesses"] == []


# ── assessments.propose_alignment ────────────────────────────────────────────────────

def _proposal(world: World, n: int = 3) -> list[dict[str, Any]]:
    keys = ["thesis", "evidence", "analysis", "mechanics", "voice", "citation"]
    return [{"key": keys[i], "description": f"The {keys[i]}",
             "levels": [{"score": s, "label": f"L{s}", "descriptor": f"Level {s}"}
                        for s in (1, 2, 3, 4)],
             "outcome_nodes": [world["out_evidence"]] if i == 1 else []}
            for i in range(n)]


async def test_propose_alignment_returns_context_ranked_by_similarity(servers, world) -> None:
    result = await _call(servers["assessments"], "assessments.propose_alignment", {
        "assignment_node": world["assignment"]})
    assert result["syllabus"]["content_id"] == world["syllabus"]
    ranked = [o["node_id"] for o in result["candidate_outcomes"]]
    assert set(ranked) == {world["out_thesis"], world["out_evidence"], world["out_other"]}
    assert ranked[0] == world["out_evidence"]
    assert next(o for o in result["candidate_outcomes"]
                if o["node_id"] == world["out_evidence"])["aligned"] is True
    assert [c["key"] for c in result["existing_criteria"]] == ["evidence", "thesis"]
    assert result["proposal"] is None


async def test_propose_alignment_validates_the_agents_criteria(servers, world) -> None:
    result = await _call(servers["assessments"], "assessments.propose_alignment", {
        "assignment_node": world["assignment"], "criteria": _proposal(world, 4),
        "max_outcomes": 1})
    assert len(result["candidate_outcomes"]) == 1
    assert [c["key"] for c in result["proposal"]["criteria"]] == [
        "thesis", "evidence", "analysis", "mechanics"]
    assert result["proposal"]["outcome_links"] == [{
        "node_id": world["out_evidence"], "title": "Support claims with cited evidence from cases",
        "score": result["proposal"]["outcome_links"][0]["score"],
        "criteria_keys": ["evidence"]}]


@pytest.mark.parametrize("mutate", [
    lambda c: c[:2],
    lambda c: c + _proposal(World(), 6)[3:] + [dict(c[0], key="extra")],
    lambda c: [dict(c[0], key="Bad Key")] + c[1:],
    lambda c: [dict(c[0], key=c[1]["key"])] + c[1:],
    lambda c: [dict(c[0], levels=list(reversed(c[0]["levels"])))] + c[1:],
    lambda c: [dict(c[0], levels=c[0]["levels"][:1])] + c[1:],
    lambda c: [dict(c[0], outcome_nodes=[str(uuid.uuid4())])] + c[1:],
    lambda c: [dict(c[0], outcome_nodes=["x' OR '1'='1"])] + c[1:],
])
async def test_propose_alignment_rejects_bad_proposals(servers, world, mutate) -> None:
    result = await _call(servers["assessments"], "assessments.propose_alignment", {
        "assignment_node": world["assignment"], "criteria": mutate(_proposal(world))})
    assert result["code"] == "validation_error"


async def test_propose_alignment_unknown_assignment(servers) -> None:
    result = await _call(servers["assessments"], "assessments.propose_alignment", {
        "assignment_node": str(uuid.uuid4())})
    assert result["code"] == "not_found"


# ── assessments.apply_alignment ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="module")
async def bare_assignment(world, pool):
    """An assignment in the course with no rubric yet; removed with whatever rubric it gets."""
    node = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, metadata)
               VALUES ($1, 'assessment_item', 'Case brief', $2)""",
            node, json.dumps({"course_id": world["course"]}),
        )
    yield str(node)
    async with pool.acquire() as conn:
        rubric = await conn.fetchval("SELECT metadata->>'rubric_id' FROM nodes WHERE id = $1",
                                     node)
        await conn.execute("DELETE FROM nodes WHERE id = $1", node)
        if rubric:
            await conn.execute("DELETE FROM rubrics WHERE id = $1::uuid", rubric)


def _accepted(world: World) -> list[dict[str, Any]]:
    proposal = _proposal(world)
    proposal[0]["outcome_nodes"] = [world["out_thesis"]]
    return proposal


async def test_apply_alignment_creates_the_rubric_and_sets_outcome_nodes(
    servers, world, pool, bare_assignment,
) -> None:
    result = await _call(servers["assessments"], "assessments.apply_alignment", {
        "assignment_node": bare_assignment, "criteria": _accepted(world),
        "requester_id": world["faculty"]})
    assert (result["rubric_created"], result["created"], result["updated"]) == (True, 3, 0)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT key, outcome_nodes FROM rubric_criteria WHERE rubric_id = $1::uuid
               ORDER BY key""", result["rubric_id"])
        node_rubric = await conn.fetchval(
            "SELECT metadata->>'rubric_id' FROM nodes WHERE id = $1::uuid", bare_assignment)
        aligned = await conn.fetch(
            """SELECT to_node FROM edges WHERE from_node = $1::uuid AND kind = 'aligned_with'
               ORDER BY to_node""", bare_assignment)
    assert {r["key"]: [str(n) for n in r["outcome_nodes"]] for r in rows} == {
        "analysis": [], "evidence": [world["out_evidence"]], "thesis": [world["out_thesis"]]}
    assert node_rubric == result["rubric_id"]
    assert sorted(str(r["to_node"]) for r in aligned) == sorted(
        [world["out_evidence"], world["out_thesis"]])
    rubric = await _call(servers["assessments"], "assessments.get_rubric",
                         {"rubric_id": result["rubric_id"]})
    assert [c["key"] for c in rubric["criteria"]] == ["thesis", "evidence", "analysis"]


async def test_apply_alignment_realigns_an_existing_scored_criterion(servers, world,
                                                                     pool) -> None:
    student = await _student(pool, world)
    await _scored(servers, world, student, 3, 2)
    result = await _call(servers["assessments"], "assessments.apply_alignment", {
        "assignment_node": world["assignment"], "requester_id": world["faculty"],
        "criteria": [{"key": "evidence",
                      "outcome_nodes": [world["out_evidence"], world["out_thesis"]]}]})
    assert (result["rubric_created"], result["created"], result["updated"]) == (False, 0, 1)
    assert result["criterion_ids"] == [world["evidence"]]
    changed = await _call(servers["assessments"], "assessments.apply_alignment", {
        "assignment_node": world["assignment"], "requester_id": world["faculty"],
        "criteria": [{**_proposal(world)[1], "outcome_nodes": [world["out_evidence"]]}]})
    assert changed["code"] == "conflict"
    async with pool.acquire() as conn:
        await conn.execute("UPDATE rubric_criteria SET outcome_nodes = $2 WHERE id = $1",
                           world.ids["evidence"], [world.ids["out_evidence"]])
        await conn.execute(
            "DELETE FROM edges WHERE from_node = $1 AND to_node = $2 AND kind = 'aligned_with'",
            world.ids["assignment"], world.ids["out_thesis"])


async def test_apply_alignment_is_for_faculty_of_the_course_only(servers, world, pool,
                                                                 bare_assignment) -> None:
    student = await _student(pool, world)
    for requester in (world["other_faculty"], world["admin"], student):
        result = await _call(servers["assessments"], "assessments.apply_alignment", {
            "assignment_node": bare_assignment, "criteria": _accepted(world),
            "requester_id": requester})
        assert result["code"] == "forbidden", result
    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT metadata->>'rubric_id' FROM nodes WHERE id = $1::uuid",
            bare_assignment) is None


async def test_apply_alignment_rejects_outcomes_of_other_courses_and_new_keys_without_levels(
    servers, world, bare_assignment,
) -> None:
    foreign = _accepted(world)
    foreign[0]["outcome_nodes"] = [str(uuid.uuid4())]
    bare = [{"key": "voice", "outcome_nodes": []}]
    for criteria in (foreign, bare):
        result = await _call(servers["assessments"], "assessments.apply_alignment", {
            "assignment_node": bare_assignment, "criteria": criteria,
            "requester_id": world["faculty"]})
        assert result["code"] == "validation_error", result


@pytest.mark.parametrize("args", [
    {"criteria": []},
    {"criteria": None},
    {"requester_id": None},
    {"assignment_node": "x' OR '1'='1"},
    {"criteria": [{"key": "Bad Key"}]},
])
async def test_apply_alignment_validates_before_touching_the_database(args) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.apply_alignment")
    base = {"assignment_node": str(uuid.uuid4()), "requester_id": str(uuid.uuid4()),
            "criteria": [{"key": "thesis", "outcome_nodes": []}]}
    assert (await handler({**base, **args}))["code"] == "validation_error"


# ── assessments.grading_status ───────────────────────────────────────────────────────

async def test_grading_status_counts_finals_by_grade_state(servers, world, pool) -> None:
    finals = []
    for _ in range(3):
        student = await _student(pool, world)
        sub = await _draft(servers, world, student, status="final")
        finals.append(uuid.UUID(sub["submission_id"]))
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO grades (submission_id, scores, feedback, is_draft, committed_at)
               VALUES ($1, '{}', '{}', true, NULL), ($2, '{}', '{}', true, NULL),
                      ($2, '{}', '{}', false, now())""",
            finals[0], finals[1],
        )
    result = await _call(servers["assessments"], "assessments.grading_status", {
        "course_id": world["course"], "assignment_id": world["assignment"]})
    [row] = result["assignments"]
    assert row["assignment_node"] == world["assignment"] and row["course_node"] == world["course"]
    assert row["title"] == "Evidence essay"
    assert row["drafts"] >= 1 and row["committed"] >= 1 and row["ungraded"] >= 1
    assert row["submissions"] == row["drafts"] + row["committed"] + row["ungraded"]
    other = await _call(servers["assessments"], "assessments.grading_status", {
        "course_id": world["other_course"]})
    assert other["assignments"] == []


@pytest.mark.parametrize("args", [
    {"course_id": "x' OR '1'='1"}, {"assignment_id": "level; DROP TABLE nodes"},
    {"course_id": 7},
])
async def test_grading_status_rejects_bad_ids(args) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.grading_status")
    result = await handler(args)
    assert result["code"] == "validation_error" and result["assignments"] == []


# ── content.generate_practice ────────────────────────────────────────────────────────

def _items(n: int = 3) -> list[dict[str, Any]]:
    return [{"type": "short_answer", "stem": f"Name a case that supports claim {i}.",
             "answer_key": {"rubric": "Any specific, relevant case."},
             "bloom_level": "apply", "difficulty": "medium"} for i in range(n)]


async def test_generate_practice_saves_a_private_aligned_set(servers, world, pool) -> None:
    student = await _student(pool, world)
    result = await _call(servers["content"], "content.generate_practice", {
        "criterion_id": world["evidence"], "student_id": student, "count": 3,
        "items": _items()})
    assert len(result["question_ids"]) == 3
    assert result["aligned_nodes"] == [world["out_evidence"]]
    async with pool.acquire() as conn:
        questions = await conn.fetch(
            "SELECT aligned_nodes, bloom_level, metadata FROM questions WHERE id = ANY($1::uuid[])",
            [uuid.UUID(q) for q in result["question_ids"]],
        )
        bank = await conn.fetchrow("SELECT course_node, metadata FROM question_banks WHERE id = $1",
                                   uuid.UUID(result["bank_id"]))
        action = await conn.fetchrow(
            "SELECT agent, action_type, subject_person FROM ai_actions WHERE id = $1",
            uuid.UUID(result["practice_set_id"]),
        )
    assert all([str(n) for n in q["aligned_nodes"]] == [world["out_evidence"]]
               and q["bloom_level"] == "apply" for q in questions)
    assert all(json.loads(q["metadata"])["student_id"] == student for q in questions)
    assert json.loads(bank["metadata"]) == {"kind": "practice"}
    assert str(bank["course_node"]) == world["course"]
    assert (action["agent"], action["action_type"], str(action["subject_person"])) == (
        "content_generator", "practice_item", student)
    listed = await _call(servers["assessments"], "assessments.search_bank", {})
    assert not set(result["question_ids"]) & {q["id"] for q in listed["questions"]}
    again = await _call(servers["content"], "content.generate_practice", {
        "criterion_id": world["evidence"], "student_id": student, "count": 3,
        "items": _items()})
    assert again["bank_id"] == result["bank_id"]


async def test_generate_practice_requires_an_enrolled_student(servers, world) -> None:
    result = await _call(servers["content"], "content.generate_practice", {
        "criterion_id": world["evidence"], "student_id": world["outsider"], "count": 3,
        "items": _items()})
    assert result["code"] == "forbidden"
    unknown = await _call(servers["content"], "content.generate_practice", {
        "criterion_id": str(uuid.uuid4()), "student_id": world["outsider"], "count": 3,
        "items": _items()})
    assert unknown["code"] == "not_found"


@pytest.mark.parametrize("args", [
    {"count": 2, "items": _items(2)},
    {"count": 6, "items": _items(6)},
    {"count": 4, "items": _items(3)},
    {"items": [dict(_items(1)[0], bloom_level="memorize")] + _items(2)},
    {"items": [dict(_items(1)[0], type="mcq")] + _items(2)},
    {"items": [dict(_items(1)[0], answer_key="x' OR '1'='1")] + _items(2)},
    {"criterion_id": "level; DROP TABLE nodes"},
])
async def test_generate_practice_rejects_bad_arguments(args) -> None:
    handler = _no_db_handler(content_tools, "content.generate_practice")
    base = {"criterion_id": str(uuid.uuid4()), "student_id": str(uuid.uuid4()), "count": 3,
            "items": _items()}
    assert (await handler({**base, **args}))["code"] == "validation_error"


async def test_generate_practice_schema_enumerates_bloom_level_and_difficulty() -> None:
    tool = next(t for t in content_tools(_NoDbPool()) if t.name == "content.generate_practice")
    item = tool.input_schema["properties"]["items"]["items"]["properties"]
    assert item["bloom_level"]["enum"] == [
        "analyze", "apply", "create", "evaluate", "remember", "understand"]
    assert item["difficulty"]["enum"] == ["easy", "hard", "medium"]


# ── assessments.record_practice_attempt ──────────────────────────────────────────────

async def _practice_set(servers, world: World, student: str) -> dict[str, Any]:
    items = [{"type": "mcq", "stem": "Which case shows unreviewed use of a model?",
              "options": {"A": "Dutch benefits", "B": "None"},
              "answer_key": {"correct": "A", "explanation": "No human review."},
              "bloom_level": "remember"},
             {"type": "mcq", "stem": "Pick a cited source.", "options": {"A": "x", "B": "y"},
              "answer_key": {"correct": ["B", "b."]}, "bloom_level": "apply"},
             *_items(1)]
    return await _call(servers["content"], "content.generate_practice", {
        "criterion_id": world["evidence"], "student_id": student, "count": 3, "items": items})


async def test_practice_attempt_is_private_evidence_with_per_item_correctness(
    servers, world, pool,
) -> None:
    student = await _student(pool, world)
    practice = await _practice_set(servers, world, student)
    q = practice["question_ids"]
    result = await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": student, "practice_set_id": practice["practice_set_id"],
        "answers": [{"question_id": q[0], "answer": " a "}, {"question_id": q[1], "answer": "A"},
                    {"question_id": q[2], "answer": "The Dutch case."}]})
    assert [i["correct"] for i in result["items"]] == [True, False, None]
    assert result["items"][0]["answer_key"]["correct"] == "A"
    assert result["score"] == 0.5 and len(result["evidence_ids"]) == 1
    async with pool.acquire() as conn:
        ev = await conn.fetchrow(
            """SELECT person_id, node_id, kind::text AS kind, score, source, visibility, payload
               FROM evidence WHERE id = $1::uuid""", result["evidence_ids"][0])
    assert (str(ev["person_id"]), str(ev["node_id"]), ev["kind"], ev["source"],
            ev["visibility"]) == (student, world["out_evidence"], "attempt", "practice",
                                  "private")
    payload = json.loads(ev["payload"])
    assert payload["practice_set_id"] == practice["practice_set_id"]
    assert [(a["answer"], a["correct"]) for a in payload["answers"]] == [
        (" a ", True), ("A", False), ("The Dutch case.", None)]


async def test_practice_attempt_on_an_unaligned_set_is_kept_on_the_assignment(
    servers, world, pool,
) -> None:
    student = await _student(pool, world)
    practice = await _practice_set(servers, world, student)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE questions SET aligned_nodes = '{}' WHERE id = ANY($1::uuid[])",
                           practice["question_ids"])
    result = await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": student, "practice_set_id": practice["practice_set_id"],
        "answers": [{"question_id": practice["question_ids"][0], "answer": "A"}]})
    assert len(result["evidence_ids"]) == 1
    async with pool.acquire() as conn:
        ev = await conn.fetchrow(
            "SELECT node_id, source, visibility FROM evidence WHERE id = $1::uuid",
            result["evidence_ids"][0])
    assert (str(ev["node_id"]), ev["source"], ev["visibility"]) == (
        world["assignment"], "practice", "private")


async def test_practice_attempts_belong_to_the_set_owner(servers, world, pool) -> None:
    student = await _student(pool, world)
    other = await _student(pool, world)
    practice = await _practice_set(servers, world, student)
    answer = [{"question_id": practice["question_ids"][0], "answer": "A"}]
    theirs = await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": other, "practice_set_id": practice["practice_set_id"], "answers": answer})
    assert theirs["code"] == "forbidden"
    stray = await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": student, "practice_set_id": practice["practice_set_id"],
        "answers": [{"question_id": str(uuid.uuid4()), "answer": "A"}]})
    assert stray["code"] == "validation_error"
    unknown = await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": student, "practice_set_id": str(uuid.uuid4()), "answers": answer})
    assert unknown["code"] == "not_found"


@pytest.mark.parametrize("args", [
    {"answers": []},
    {"answers": [{"question_id": "x' OR '1'='1", "answer": "A"}]},
    {"answers": [{"question_id": str(uuid.uuid4()), "answer": ""}]},
    {"practice_set_id": None},
])
async def test_practice_attempt_validates_before_touching_the_database(args) -> None:
    handler = _no_db_handler(assessments_tools, "assessments.record_practice_attempt")
    base = {"person_id": str(uuid.uuid4()), "practice_set_id": str(uuid.uuid4()),
            "answers": [{"question_id": str(uuid.uuid4()), "answer": "A"}]}
    assert (await handler({**base, **args}))["code"] == "validation_error"


async def test_practice_evidence_is_listed_only_for_the_learner(servers, world, pool,
                                                                monkeypatch) -> None:
    monkeypatch.delenv("LMS_AS_OF", raising=False)
    student = await _student(pool, world)
    practice = await _practice_set(servers, world, student)
    await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": student, "practice_set_id": practice["practice_set_id"],
        "answers": [{"question_id": practice["question_ids"][0], "answer": "A"}]})
    seen = {}
    for who, requester in (("self", student), ("faculty", world["faculty"]), ("none", None)):
        args = {"person_id": student, "since_days": 1}
        if requester:
            args["requester_id"] = requester
        listed = await _call(servers["assessments"], "assessments.list_recent_evidence", args)
        seen[who] = [(e["kind"], e["visibility"]) for e in listed["evidence"]]
    assert seen == {"self": [("attempt", "private")], "faculty": [], "none": []}


async def test_practice_evidence_reaches_student_context_only_for_the_learner(
        servers, world, pool, monkeypatch) -> None:
    monkeypatch.delenv("LMS_AS_OF", raising=False)
    student = await _student(pool, world)
    practice = await _practice_set(servers, world, student)
    await _call(servers["assessments"], "assessments.record_practice_attempt", {
        "person_id": student, "practice_set_id": practice["practice_set_id"],
        "answers": [{"question_id": practice["question_ids"][0], "answer": "A"}]})
    seen = {}
    for who, requester in (("self", student), ("faculty", world["faculty"]), ("none", None)):
        args = {"person_id": student, "course_id": world["course"]}
        if requester:
            args["requester_id"] = requester
        ctx = await _call(servers["roster"], "roster.get_student_context", args)
        seen[who] = [(e["source"], e["visibility"]) for e in ctx["recent_evidence"]]
    assert seen == {"self": [("practice", "private")], "faculty": [], "none": []}


async def test_student_context_keeps_course_evidence_for_staff(servers, world, pool,
                                                               monkeypatch) -> None:
    monkeypatch.delenv("LMS_AS_OF", raising=False)
    student = await _student(pool, world)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO evidence (person_id, node_id, kind, score, source, observed_at,
                                     visibility)
               VALUES ($1::uuid, $2::uuid, 'artifact_submission', 0.8, 'grading_assistant',
                       now() - interval '1 minute', 'course')""",
            student, world["assignment"])
    ctx = await _call(servers["roster"], "roster.get_student_context", {
        "person_id": student, "course_id": world["course"], "requester_id": world["faculty"]})
    assert [(e["kind"], e["source"], e["visibility"]) for e in ctx["recent_evidence"]] == [
        ("artifact_submission", "grading_assistant", "course")]


# ── graph.subgraph_for_outcomes ──────────────────────────────────────────────────────

async def test_subgraph_for_outcomes_stays_below_the_course(servers, world) -> None:
    result = await _call(servers["content"], "graph.subgraph_for_outcomes", {
        "outcome_ids": [world["out_evidence"]]})
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {world["out_evidence"], world["concept"], world["module"], world["assignment"]}
    assert {(e["src"], e["dst"], e["kind"]) for e in result["edges"]} == {
        (world["concept"], world["out_evidence"], "aligned_with"),
        (world["assignment"], world["out_evidence"], "aligned_with"),
        (world["concept"], world["module"], "part_of"),
    }
    shallow = await _call(servers["content"], "graph.subgraph_for_outcomes", {
        "outcome_ids": [world["out_evidence"]], "depth": 1})
    assert world["module"] not in {n["id"] for n in shallow["nodes"]}


@pytest.mark.parametrize("args", [
    {"outcome_ids": []}, {"outcome_ids": ["x' OR '1'='1"]}, {"outcome_ids": "abc"},
    {"outcome_ids": [str(uuid.uuid4())], "depth": 0},
    {"outcome_ids": [str(uuid.uuid4())], "depth": 5},
])
async def test_subgraph_for_outcomes_rejects_bad_arguments(args) -> None:
    result = await _no_db_handler(content_tools, "graph.subgraph_for_outcomes")(args)
    assert result["code"] == "validation_error" and result["nodes"] == []


async def test_subgraph_for_outcomes_rejects_non_outcome_nodes(servers, world) -> None:
    result = await _call(servers["content"], "graph.subgraph_for_outcomes", {
        "outcome_ids": [world["concept"]]})
    assert result["code"] == "validation_error"
