"""AI Review aggregation, the generated-items log and the evaluator export (spec.md §6.5)."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from engine.api.measurement import to_csv
from engine.auth.access_log import AccessEntry
from engine.measurement import (
    ActionRecord,
    DecisionRecord,
    LinkRecord,
    Program,
    criterion_changes,
    criterion_uuid,
    decision_rates,
    link_change,
    pseudonymous_id,
    summarize,
)
from engine.tests.auth_fakes import CS101, ENG102, MATH201, AuthWorld
from engine.tests.measurement_fakes import InMemoryMeasurementStore
from engine.tests.object_fakes import InMemoryAccessLog

BASE = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
RUBRIC = str(uuid.uuid4())
THESIS_ID = str(uuid.uuid4())


def _id() -> str:
    return str(uuid.uuid4())


@dataclass
class Data:
    store: InMemoryMeasurementStore
    ids: dict[str, str]


def build(world: AuthWorld) -> Data:
    emma, noah = world.people["student"].id, world.people["noah"].id
    torres, chen = world.people["faculty"].id, world.people["chen"].id
    store = InMemoryMeasurementStore(criteria={(RUBRIC, "thesis"): THESIS_ID})
    ids: dict[str, str] = {}

    def action(name: str, agent: str, kind: str, course: str, subject: str | None,
               output: dict, hours: int, **extra) -> str:
        ids[name] = _id()
        store.actions.append(ActionRecord(
            id=ids[name], agent=agent, action_type=kind, output=output,
            created_at=BASE + timedelta(hours=hours), subject_person=subject,
            course_node=course, **extra))
        return ids[name]

    def decide(name: str, decision: str, by: str, diff: dict | None = None,
               hours: int = 100) -> None:
        store.decisions.append(DecisionRecord(
            id=_id(), ai_action_id=ids[name], decided_by=by, decision=decision,
            decided_at=BASE + timedelta(hours=hours), decided_by_name="Someone", diff=diff))

    def link(name: str, delta: dict) -> None:
        store.links.append(LinkRecord(ids[name], BASE + timedelta(days=5),
                                      evidence_id=_id(), delta=delta))

    cs, eng, math = CS101.course_id, ENG102.course_id, MATH201.course_id
    action("accepted", "grading_assistant", "grade_draft", cs, emma,
           {"rubric_id": RUBRIC, "scores": {"thesis": 3, "evidence": 2}}, 1,
           sources=({"type": "rubric", "id": RUBRIC},), target_type="grades",
           target_id=_id())
    decide("accepted", "accepted", torres)
    link("accepted", {"kind": "criterion", "change": 1.0})

    action("edited", "grading_assistant", "grade_draft", cs, emma,
           {"rubric_id": RUBRIC, "scores": {"thesis": 4, "evidence": 3}}, 2)
    decide("edited", "edited", torres,
           {"criteria": {"thesis": {"before": 4, "after": 3, "delta": -1}}, "changed": True})
    link("edited", {"before": 2, "after": 2.5})

    action("rejected", "grading_assistant", "grade_draft", cs, emma,
           {"scores": {"thesis": 2, "evidence": 3}}, 3,
           sources=({"type": "rubric", "id": RUBRIC},))
    decide("rejected", "rejected", torres,
           {"criteria": [{"key": "evidence", "rubric_id": RUBRIC, "ai_score": 3,
                          "final_score": 1, "delta": -2}]})
    link("rejected", {"criterion": "evidence", "before": 1, "after": 3, "max": 4})

    action("undecided", "grading_assistant", "grade_draft", cs, emma,
           {"scores": {"thesis": 2}}, 4)
    action("generation", "content_generator", "generation", cs, None,
           {"tool": "content.save_skill"}, 5, sources=({"type": "node", "id": cs},))
    decide("generation", "edited", torres, {"fields": {}, "changed": True})
    action("recommendation", "tutor", "recommendation", cs, emma,
           {"kind": "practice", "note": f"for {emma}"}, 6)
    decide("recommendation", "snoozed", emma, hours=50)
    decide("recommendation", "dismissed", emma, hours=60)

    action("noah", "grading_assistant", "grade_draft", eng, noah,
           {"scores": {"thesis": 1}, "student_name": "Noah Brown",
            "person_id": noah}, 7, target_type="persons", target_id=noah)
    decide("noah", "accepted", noah)
    action("math", "grading_assistant", "grade_draft", math, emma, {"scores": {}}, 8)
    decide("math", "accepted", chen)
    store.titles[("node", cs)] = "CS 101"
    return Data(store, ids)


@pytest.fixture
def data(auth_world: AuthWorld, auth_app, monkeypatch: pytest.MonkeyPatch) -> Data:
    monkeypatch.setenv("PII_PSEUDONYM_SALT", "test-salt")
    built = build(auth_world)
    auth_app.state.measurement_store = built.store
    return built


def _cs101(data: Data) -> tuple[list[ActionRecord], dict, dict]:
    actions = [a for a in data.store.actions if a.course_node == CS101.course_id]
    decisions: dict[str, list[DecisionRecord]] = {}
    for d in sorted(data.store.decisions, key=lambda d: d.decided_at):
        decisions.setdefault(d.ai_action_id, []).append(d)
    links: dict[str, list[LinkRecord]] = {}
    for link in data.store.links:
        links.setdefault(link.ai_action_id, []).append(link)
    return actions, decisions, links


def _resolve(rubric: str | None, key: str) -> str:
    return THESIS_ID if (rubric, key) == (RUBRIC, "thesis") else criterion_uuid(rubric, key)


# --- pure aggregation ----------------------------------------------------------------------


def test_decision_rates_are_over_decided_items():
    rates = decision_rates(["accepted", "edited", "rejected", "dismissed", None])
    assert rates == {"agent": None, "action_type": None, "total": 5, "accepted": 1,
                     "edited": 1, "rejected": 1, "other": 1, "undecided": 1,
                     "acceptance_rate": 0.25, "edit_rate": 0.25, "reject_rate": 0.25}


def test_decision_rates_are_null_with_nothing_decided():
    rates = decision_rates([None, None])
    assert rates["acceptance_rate"] is None and rates["undecided"] == 2


def test_criterion_changes_reads_engine_and_seed_diff_shapes():
    assert criterion_changes({"criteria": {"thesis": {"before": 3, "after": 2, "delta": -1}}}
                             ) == {"thesis": (-1.0, None)}
    assert criterion_changes({"criteria": [{"key": "style", "rubric_id": RUBRIC, "delta": 2}]}
                             ) == {"style": (2.0, RUBRIC)}
    assert criterion_changes({"criteria": {"tone": {"before": "a", "after": "b",
                                                    "delta": None}}}) == {"tone": (None, None)}
    assert criterion_changes({"fields": {}}) is None
    assert criterion_changes(None) is None


@pytest.mark.parametrize(("delta", "expected"), [
    ({"change": 0.5, "before": 0, "after": 9}, 0.5),
    ({"before": 1, "after": 3}, 2.0),
    ({"before": None, "after": 3}, None),
    ({"change": True}, None),
    (None, None),
])
def test_link_change(delta, expected):
    assert link_change(delta) == expected


def test_summarize_rates_by_agent_and_action_type(data):
    body = summarize(*_cs101(data), _resolve)
    rows = {(r["agent"], r["action_type"]): r for r in body["rates"]}
    assert set(rows) == {("grading_assistant", "grade_draft"),
                         ("content_generator", "generation"), ("tutor", "recommendation")}
    grade = rows[("grading_assistant", "grade_draft")]
    assert (grade["total"], grade["accepted"], grade["edited"], grade["rejected"],
            grade["undecided"]) == (4, 1, 1, 1, 1)
    assert grade["acceptance_rate"] == grade["edit_rate"] == 0.3333
    assert rows[("content_generator", "generation")]["edit_rate"] == 1.0
    assert rows[("tutor", "recommendation")]["other"] == 1


def test_summarize_criterion_changes_count_unchanged_criteria_as_zero(data):
    body = summarize(*_cs101(data), _resolve)
    changes = {c["criterion_key"]: c for c in body["criterion_score_changes"]}
    assert changes["thesis"] == {"criterion_id": THESIS_ID, "criterion_key": "thesis", "n": 3,
                                 "mean_delta": -0.333}
    assert changes["evidence"]["criterion_id"] == criterion_uuid(RUBRIC, "evidence")
    assert (changes["evidence"]["n"], changes["evidence"]["mean_delta"]) == (3, -0.667)


def test_summarize_most_edited_criteria(data):
    body = summarize(*_cs101(data), _resolve)
    assert [(c["criterion_key"], c["edit_count"], c["edit_rate"])
            for c in body["most_edited_criteria"]] == [("evidence", 1, 0.3333),
                                                       ("thesis", 1, 0.3333)]


def test_summarize_learning_delta_by_latest_decision(data):
    body = summarize(*_cs101(data), _resolve)
    assert body["learning_delta_by_decision"] == {
        "accepted": {"n": 1, "mean_delta": 1.0}, "edited": {"n": 1, "mean_delta": 0.5},
        "rejected": {"n": 1, "mean_delta": 2.0}}


def test_summarize_empty():
    body = summarize([], {}, {}, _resolve)
    assert body["rates"] == [] and body["most_edited_criteria"] == []
    assert body["learning_delta_by_decision"]["accepted"] == {"n": 0, "mean_delta": None}


def test_rejected_draft_without_a_diff_has_no_criterion_stats():
    action = ActionRecord(id=_id(), agent="g", action_type="grade_draft",
                          output={"scores": {"thesis": 1}}, created_at=BASE)
    decision = DecisionRecord(_id(), action.id, _id(), "rejected", BASE)
    body = summarize([action], {action.id: [decision]}, {}, _resolve)
    assert body["criterion_score_changes"] == [] and body["rates"][0]["rejected"] == 1


def test_pseudonymous_id_is_a_stable_uuid(monkeypatch):
    monkeypatch.setenv("PII_PSEUDONYM_SALT", "one")
    person = _id()
    first = pseudonymous_id(person)
    assert uuid.UUID(first) and first == pseudonymous_id(person) and first != person
    monkeypatch.setenv("PII_PSEUDONYM_SALT", "two")
    assert pseudonymous_id(person) != first


# --- course measurement --------------------------------------------------------------------


async def test_course_measurement_shape(authed_client, data):
    client = await authed_client("faculty")
    resp = await client.get(f"/api/measurement/courses/{CS101.course_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == {"type": "course", "id": CS101.course_id, "title": "CS 101"}
    assert body["from"] is None and body["to"]
    assert {r["action_type"] for r in body["rates"]} == {"grade_draft", "generation",
                                                         "recommendation"}
    assert body["learning_delta_by_decision"]["edited"]["n"] == 1
    assert "offloading" not in body


async def test_course_measurement_date_range(authed_client, data):
    client = await authed_client("faculty")
    resp = await client.get(f"/api/measurement/courses/{CS101.course_id}", params={
        "from": (BASE + timedelta(hours=2)).isoformat(),
        "to": (BASE + timedelta(hours=4)).isoformat()})
    grade = next(r for r in resp.json()["rates"] if r["action_type"] == "grade_draft")
    assert (grade["total"], grade["edited"], grade["rejected"]) == (2, 1, 1)


async def test_course_measurement_rejects_empty_range(authed_client, data):
    client = await authed_client("faculty")
    resp = await client.get(f"/api/measurement/courses/{CS101.course_id}",
                            params={"from": BASE.isoformat(), "to": BASE.isoformat()})
    assert resp.status_code == 422


async def test_unknown_course_is_404_for_admin_and_403_otherwise(authed_client, data):
    admin, faculty = await authed_client("admin"), await authed_client("faculty")
    assert (await admin.get(f"/api/measurement/courses/{_id()}")).status_code == 404
    assert (await faculty.get(f"/api/measurement/courses/{_id()}")).status_code == 403


async def test_measurement_is_503_without_a_database(authed_client, auth_app):
    client = await authed_client("faculty")
    resp = await client.get(f"/api/measurement/courses/{CS101.course_id}")
    assert resp.status_code == 503


# --- rollup --------------------------------------------------------------------------------


async def test_admin_rollup_is_institution_wide(authed_client, data):
    client = await authed_client("admin")
    body = (await client.get("/api/measurement/rollup")).json()
    assert body["scope"]["type"] == "institution"
    totals = {row["course"]["course_id"]: row["totals"] for row in body["per_course"]}
    assert set(totals) == {CS101.course_id, ENG102.course_id, MATH201.course_id}
    assert totals[CS101.course_id]["total"] == 6
    assert totals[ENG102.course_id]["accepted"] == 1
    assert body["compliance"] == {"mismatches_count": 0}
    grade = next(r for r in body["rates"] if r["action_type"] == "grade_draft")
    assert grade["total"] == 6


async def test_program_lead_rollup_without_a_program_is_institution_scope_and_denied(
    authed_client, data
):
    client = await authed_client("program_lead")
    assert (await client.get("/api/measurement/rollup")).status_code == 403


async def test_program_lead_rollup_for_a_program_they_lead(authed_client, auth_world, data):
    program = _id()
    data.store.programs[program] = Program(program, "Computing",
                                           frozenset({auth_world.people["faculty"].id}),
                                           frozenset({CS101.course_id, ENG102.course_id}))
    client = await authed_client("program_lead")
    body = (await client.get("/api/measurement/rollup", params={"program_id": program})).json()
    assert body["scope"] == {"type": "program", "id": program, "title": "Computing"}
    assert {r["course"]["course_id"] for r in body["per_course"]} == {CS101.course_id,
                                                                      ENG102.course_id}


async def test_program_lead_cannot_roll_up_a_program_they_do_not_lead(authed_client, data):
    program = _id()
    data.store.programs[program] = Program(program, "Other", frozenset(),
                                           frozenset({ENG102.course_id}))
    client = await authed_client("program_lead")
    resp = await client.get("/api/measurement/rollup", params={"program_id": program})
    assert resp.status_code == 403
    admin = await authed_client("admin")
    assert (await admin.get("/api/measurement/rollup",
                            params={"program_id": program})).status_code == 200


# --- the generated-items log ---------------------------------------------------------------


async def _list(client, **params) -> list[dict]:  # noqa: ANN001
    resp = await client.get("/api/ai-actions", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def test_student_sees_only_items_about_them(authed_client, auth_world, data):
    items = await _list(await authed_client("student"))
    emma = auth_world.people["student"].id
    assert items and all(i["subject_person_id"] == emma for i in items)
    assert data.ids["noah"] not in {i["id"] for i in items}
    assert await _list(await authed_client("student"),
                       subject_person_id=auth_world.people["noah"].id) == []


async def test_faculty_sees_own_courses_newest_first(authed_client, data):
    items = await _list(await authed_client("faculty"))
    assert {i["course_id"] for i in items} == {CS101.course_id}
    assert [i["created_at"] for i in items] == sorted((i["created_at"] for i in items),
                                                      reverse=True)


async def test_advisor_sees_items_about_advisees(authed_client, auth_world, data):
    items = await _list(await authed_client("advisor"))
    assert {i["subject_person_id"] for i in items} == {auth_world.people["student"].id}


async def test_log_filters(authed_client, data):
    admin = await authed_client("admin")
    assert {i["id"] for i in await _list(admin, decision="none")} == {data.ids["undecided"]}
    assert {i["id"] for i in await _list(admin, decision="dismissed")} == {
        data.ids["recommendation"]}
    assert {i["agent"] for i in await _list(admin, agent="tutor")} == {"tutor"}
    assert {i["action_type"] for i in await _list(admin, action_type="generation")} == {
        "generation"}
    assert {i["course_id"] for i in await _list(admin, course_id=ENG102.course_id)} == {
        ENG102.course_id}
    faculty = await authed_client("faculty")
    assert await _list(faculty, course_id=ENG102.course_id) == []


async def test_log_program_filter(authed_client, data):
    program = _id()
    data.store.programs[program] = Program(program, "P", frozenset(),
                                           frozenset({MATH201.course_id}))
    items = await _list(await authed_client("admin"), program_id=program)
    assert {i["id"] for i in items} == {data.ids["math"]}
    assert await _list(await authed_client("admin"), program_id=_id()) == []


async def test_log_pages_with_a_cursor(authed_client, data):
    admin = await authed_client("admin")
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        body = (await admin.get("/api/ai-actions", params=params)).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(data.store.actions)


async def test_log_rejects_a_bad_cursor_and_limit(authed_client, data):
    admin = await authed_client("admin")
    assert (await admin.get("/api/ai-actions", params={"cursor": "nope"})).status_code == 422
    assert (await admin.get("/api/ai-actions", params={"limit": 0})).status_code == 422
    assert (await admin.get("/api/ai-actions", params={"limit": 201})).status_code == 422


async def test_ai_action_detail_carries_provenance(authed_client, data):
    client = await authed_client("faculty")
    resp = await client.get(f"/api/ai-actions/{data.ids['accepted']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"] == [{"type": "rubric", "id": RUBRIC, "title": None}]
    assert [d["decision"] for d in body["decisions"]] == ["accepted"]
    assert body["outcome_links"][0]["delta"] == {"kind": "criterion", "change": 1.0}
    assert body["policies"] == [] and body["target_type"] == "grades"


async def test_ai_action_source_titles_and_decision_order(authed_client, data):
    client = await authed_client("faculty")
    gen = (await client.get(f"/api/ai-actions/{data.ids['generation']}")).json()
    assert gen["sources"][0]["title"] == "CS 101"
    rec = (await client.get(f"/api/ai-actions/{data.ids['recommendation']}")).json()
    assert [d["decision"] for d in rec["decisions"]] == ["snoozed", "dismissed"]


async def test_ai_action_detail_404(authed_client, data):
    client = await authed_client("admin")
    assert (await client.get(f"/api/ai-actions/{_id()}")).status_code == 404


# --- the learner-facing view (student, advisor) ---------------------------------------------


def _commit(data: Data, *names: str) -> None:
    for name in names:
        action = next(a for a in data.store.actions if a.id == data.ids[name])
        assert action.target_type == "grades" and action.target_id
        data.store.committed_grades.add(action.target_id)


def _feedback(data: Data, auth_world: AuthWorld, *, released: bool) -> str:
    fid = _id()
    data.store.actions.append(ActionRecord(
        id=fid, agent="grading_assistant", action_type="criterion_feedback",
        output={"criterion": "thesis", "feedback_md": "Tighten the claim"},
        created_at=BASE + timedelta(hours=9), subject_person=auth_world.people["student"].id,
        course_node=CS101.course_id))
    if released:
        data.store.released_actions.add(fid)
    return fid


@pytest.mark.parametrize("actor", ["student", "advisor"])
async def test_learner_view_lists_only_committed_unrejected_grade_drafts(
        authed_client, data, actor):
    _commit(data, "accepted")
    rejected = next(a for a in data.store.actions if a.id == data.ids["rejected"])
    data.store.actions.remove(rejected)
    grade = _id()
    data.store.actions.append(replace(rejected, target_type="grades", target_id=grade))
    data.store.committed_grades.add(grade)

    ids = {i["id"] for i in await _list(await authed_client(actor))}

    assert data.ids["accepted"] in ids and data.ids["recommendation"] in ids
    assert not ids & {data.ids["edited"], data.ids["rejected"], data.ids["undecided"],
                      data.ids["math"]}


@pytest.mark.parametrize("actor", ["student", "advisor"])
async def test_learner_view_hides_criterion_feedback_until_released(
        authed_client, auth_world, data, actor):
    held = _feedback(data, auth_world, released=False)
    released = _feedback(data, auth_world, released=True)

    client = await authed_client(actor)
    ids = {i["id"] for i in await _list(client)}

    assert released in ids and held not in ids
    assert (await client.get(f"/api/ai-actions/{held}")).status_code == 404


@pytest.mark.parametrize("actor", ["student", "advisor"])
async def test_learner_view_detail_of_an_uncommitted_draft_is_404(authed_client, data, actor):
    client = await authed_client(actor)
    assert (await client.get(f"/api/ai-actions/{data.ids['undecided']}")).status_code == 404
    faculty = await authed_client("faculty")
    assert (await faculty.get(f"/api/ai-actions/{data.ids['undecided']}")).status_code == 200


@pytest.mark.parametrize("actor", ["student", "advisor"])
async def test_learner_view_strips_decision_diff_and_reason(authed_client, data, actor):
    _commit(data, "accepted")
    data.store.decisions.append(DecisionRecord(
        id=_id(), ai_action_id=data.ids["accepted"], decided_by=_id(), decision="edited",
        decided_at=BASE + timedelta(hours=200), diff={"criteria": {"thesis": {"delta": -1}}},
        reason="Too generous on thesis"))

    client = await authed_client(actor)
    detail = (await client.get(f"/api/ai-actions/{data.ids['accepted']}")).json()
    listed = next(i for i in await _list(client) if i["id"] == data.ids["accepted"])

    for item in (detail, listed):
        assert [d["decision"] for d in item["decisions"]] == ["accepted", "edited"]
        assert all(d["diff"] is None and d["reason"] is None for d in item["decisions"])
    assert "Too generous" not in str(detail)
    faculty = (await (await authed_client("faculty")).get(
        f"/api/ai-actions/{data.ids['accepted']}")).json()
    assert faculty["decisions"][-1]["reason"] == "Too generous on thesis"


async def test_learner_view_pages_past_hidden_items(authed_client, data):
    client = await authed_client("student")
    first = (await client.get("/api/ai-actions", params={"limit": 1})).json()
    assert [i["id"] for i in first["items"]] == [data.ids["recommendation"]]
    assert first["next_cursor"] is None


async def test_program_lead_sees_pseudonymous_learners_outside_taught_courses(
        authed_client, auth_world, data):
    auth_world.directory.programs[auth_world.people["faculty"].id] = frozenset(
        {CS101.course_id, ENG102.course_id})
    items = {i["id"]: i for i in await _list(await authed_client("program_lead"))}
    noah = auth_world.people["noah"].id
    eng = items[data.ids["noah"]]
    assert eng["subject_person_id"] == pseudonymous_id(noah)
    assert eng["target_id"] == pseudonymous_id(noah)
    assert eng["output"]["student_name"].startswith("Student-")
    assert noah not in str(eng)
    cs = items[data.ids["accepted"]]
    assert cs["subject_person_id"] == auth_world.people["student"].id


# --- export --------------------------------------------------------------------------------


async def test_export_json_has_all_three_tables(authed_client, auth_world, data):
    client = await authed_client("faculty")
    resp = await client.get("/api/measurement/export", params={"course_id": CS101.course_id})
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment; filename=")
    body = resp.json()
    assert body["course_id"] == CS101.course_id and body["generated_at"]
    assert len(body["ai_actions"]) == 6
    assert [a["created_at"] for a in body["ai_actions"]] == sorted(
        a["created_at"] for a in body["ai_actions"])
    assert len(body["human_decisions"]) == 6 and len(body["outcome_links"]) == 3
    assert auth_world.people["student"].id in {a["subject_person_id"]
                                                for a in body["ai_actions"]}


@pytest.mark.parametrize(("table", "column", "rows"), [
    ("ai_actions", "action_type", 6), ("human_decisions", "decision", 6),
    ("outcome_links", "delta", 3)])
async def test_export_csv_one_table(authed_client, data, table, column, rows):
    client = await authed_client("faculty")
    resp = await client.get("/api/measurement/export", params={
        "course_id": CS101.course_id, "format": "csv", "table": table})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert f"-{table}.csv" in resp.headers["content-disposition"]
    parsed = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(parsed) == rows and all(r[column] for r in parsed)


async def test_export_csv_serializes_json_columns(authed_client, data):
    client = await authed_client("faculty")
    resp = await client.get("/api/measurement/export", params={
        "course_id": CS101.course_id, "format": "csv", "table": "ai_actions"})
    row = next(r for r in csv.DictReader(io.StringIO(resp.text))
               if r["id"] == data.ids["accepted"])
    assert row["sources"].startswith("[{") and row["output"].startswith("{")


@pytest.mark.parametrize("text", ["=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)",
                                  "\tcmd", "\rcmd"])
def test_csv_cells_that_would_run_as_formulas_are_quoted(text):
    rows = list(csv.reader(io.StringIO(to_csv([{"reason": text}], ("reason",)), newline="")))
    assert rows == [["reason"], ["'" + text]]


def test_csv_leaves_ordinary_cells_alone():
    out = to_csv([{"a": "plain", "b": -2, "c": None, "d": {"k": "=x"}}], ("a", "b", "c", "d"))
    assert list(csv.reader(io.StringIO(out, newline="")))[1] == ["plain", "-2", "",
                                                                 '{"k":"=x"}']


async def test_export_pseudonymizes_without_learner_scope(authed_client, auth_world, data):
    auth_world.directory.programs[auth_world.people["faculty"].id] = frozenset(
        {CS101.course_id, ENG102.course_id})
    client = await authed_client("program_lead")
    resp = await client.get("/api/measurement/export", params={"course_id": ENG102.course_id})
    assert resp.status_code == 200
    body = resp.json()
    noah = auth_world.people["noah"].id
    assert noah not in resp.text and "Noah Brown" not in resp.text
    assert body["ai_actions"][0]["subject_person_id"] == pseudonymous_id(noah)
    assert body["human_decisions"][0]["decided_by"] == pseudonymous_id(noah)
    assert body["human_decisions"][0]["decided_by_name"].startswith("Student-")


async def test_export_keeps_ids_for_course_faculty_and_admin(authed_client, auth_world, data):
    admin = await authed_client("admin")
    body = (await admin.get("/api/measurement/export",
                            params={"course_id": ENG102.course_id})).json()
    assert body["ai_actions"][0]["subject_person_id"] == auth_world.people["noah"].id


async def test_export_logs_one_access_row_per_subject(authed_client, auth_world, auth_app,
                                                      data):
    access_log = InMemoryAccessLog()
    auth_app.state.access_log = access_log
    emma = auth_world.people["student"].id
    extra = next(a for a in data.store.actions if a.id == data.ids["undecided"])
    data.store.actions.append(replace(extra, id=_id()))

    client = await authed_client("faculty")
    resp = await client.get("/api/measurement/export", params={
        "course_id": CS101.course_id, "format": "csv", "table": "human_decisions"})

    assert resp.status_code == 200
    assert access_log.entries == [AccessEntry(auth_world.people["faculty"].id, emma,
                                              "ai_actions", None, "measurement_export")]


async def test_export_succeeds_when_the_access_log_write_fails(authed_client, auth_app, data):
    auth_app.state.access_log = InMemoryAccessLog(fail=True)
    client = await authed_client("faculty")
    resp = await client.get("/api/measurement/export", params={"course_id": CS101.course_id})
    assert resp.status_code == 200


async def test_export_requires_course_id(authed_client, data):
    client = await authed_client("admin")
    assert (await client.get("/api/measurement/export")).status_code == 422
