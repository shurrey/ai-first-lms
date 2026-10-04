"""/api/submissions*, /api/feedback* and /api/improvement against an in-memory store and
recorded MCP calls; the background feedback run uses a stub agent runner."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import engine.agents.runner as runner_mod
from engine.agents.runner import StubAgentRunner
from engine.graph.dispatch import set_agent_runner
from engine.tests.auth_fakes import CS101, ENG102, MATH201
from engine.tests.formative_fakes import T0, InMemoryFormativeStore, RecordingTools, new_id
from engine.tests.object_fakes import InMemoryAccessLog


@pytest.fixture
def store(auth_world) -> InMemoryFormativeStore:
    names = {p.id: p.display_name for p in auth_world.people.values()}
    return InMemoryFormativeStore(names=names)


@pytest.fixture
def tools(monkeypatch) -> RecordingTools:
    recorder = RecordingTools()
    monkeypatch.setattr(runner_mod, "_call_mcp_json", recorder)
    return recorder


@pytest.fixture
def stub_runner():
    runner = StubAgentRunner()
    set_agent_runner(runner)
    yield runner
    set_agent_runner(None)


@pytest.fixture
def app(auth_app, store, tools, stub_runner):
    auth_app.state.formative_store = store
    auth_app.state.access_log = InMemoryAccessLog()
    return auth_app


@pytest.fixture
def ids(auth_world) -> dict[str, str]:
    return {key: p.id for key, p in auth_world.people.items()}


async def _drain(app: Any) -> None:
    for _ in range(200):
        if not app.state.background_tasks:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("background work did not finish")


# --- POST /api/submissions -----------------------------------------------------------------


async def test_a_student_submits_a_draft_as_themself_and_feedback_starts(
        app, store, tools, stub_runner, authed_client, ids):
    assignment = store.add_assignment(CS101.course_id)

    def submit(args):
        row = store.add_submission(store.assignments[args["assignment_node"]],
                                   args["person_id"], body=args["body_md"])
        return {"submission_id": row.id, "version": 1, "status": "draft"}

    tools.replies["assessments.submit"] = submit
    client = await authed_client("student")

    resp = await client.post("/api/submissions", json={
        "assignment_id": assignment.id, "status": "draft", "body_md": "My essay."})
    await _drain(app)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["person_id"], body["feedback_status"], body["body_md"]) == (
        ids["student"], "pending", "My essay.")
    assert tools.calls_to("assessments.submit") == [{
        "person_id": ids["student"], "assignment_node": assignment.id, "body_md": "My essay.",
        "attachments": [], "status": "draft"}]
    assert [c["agent"] for c in stub_runner.calls] == ["feedback"]


async def test_submit_refusals(app, store, tools, authed_client):
    cs = store.add_assignment(CS101.course_id)
    eng = store.add_assignment(ENG102.course_id)
    student = await authed_client("student")
    faculty = await authed_client("faculty")
    body = {"status": "draft", "body_md": "x"}

    assert (await faculty.post("/api/submissions",
                               json={**body, "assignment_id": cs.id})).status_code == 403
    assert (await student.post("/api/submissions",
                               json={**body, "assignment_id": eng.id})).status_code == 403
    assert (await student.post("/api/submissions",
                               json={**body, "assignment_id": new_id()})).status_code == 404
    assert (await student.post("/api/submissions",
                               json={**body, "assignment_id": "nope"})).status_code == 422
    for code, status in (("conflict", 409), ("validation_error", 422), (None, 502)):
        tools.replies["assessments.submit"] = {"error": "refused", "code": code}
        resp = await student.post("/api/submissions", json={**body, "assignment_id": cs.id})
        assert resp.status_code == status


# --- GET /api/submissions ------------------------------------------------------------------


async def test_submissions_carry_their_assignment_title(app, store, authed_client, ids):
    sub = store.add_submission(store.add_assignment(CS101.course_id), ids["student"])
    client = await authed_client("student")

    listed = (await client.get("/api/submissions")).json()["items"]
    one = (await client.get(f"/api/submissions/{sub.id}")).json()

    assert [i["assignment_title"] for i in listed] == ["Essay 1"]
    assert one["assignment_title"] == "Essay 1"


async def test_listing_is_scoped_by_role(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    math = store.add_assignment(MATH201.course_id)
    mine = store.add_submission(cs, ids["student"])
    store.add_submission(math, ids["student"])
    store.add_submission(cs, ids["noah"])

    student = await authed_client("student")
    own = (await student.get("/api/submissions")).json()["items"]
    assert {i["person_id"] for i in own} == {ids["student"]}
    assert all(i["body_md"] is None for i in own)

    faculty = await authed_client("faculty")
    taught = (await faculty.get("/api/submissions")).json()["items"]
    assert {i["course_id"] for i in taught} == {CS101.course_id}
    assert (await faculty.get("/api/submissions",
                              params={"course_id": MATH201.course_id})).status_code == 403

    advisor = await authed_client("advisor")
    assert (await advisor.get("/api/submissions")).status_code == 403
    advisee = (await advisor.get("/api/submissions",
                                 params={"person_id": ids["student"]})).json()["items"]
    assert len(advisee) == 2
    assert (await (await authed_client("program_lead")).get(
        "/api/submissions")).status_code == 403
    assert mine.id in {i["id"] for i in own}


async def test_listing_pages_with_a_cursor(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    for _ in range(3):
        store.add_submission(cs, ids["student"])
    client = await authed_client("student")

    first = (await client.get("/api/submissions", params={"limit": 2})).json()
    second = (await client.get("/api/submissions",
                               params={"limit": 2, "cursor": first["next_cursor"]})).json()

    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert (await client.get("/api/submissions", params={"cursor": "%%%"})).status_code == 422


async def test_latest_versions_only_unless_all_versions(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    v1 = store.add_submission(cs, ids["student"])
    v2 = store.add_submission(cs, ids["student"], parent=v1)
    client = await authed_client("student")

    latest = (await client.get("/api/submissions")).json()["items"]
    every = (await client.get("/api/submissions", params={"all_versions": "true"})).json()

    assert [i["id"] for i in latest] == [v2.id]
    assert {i["id"] for i in every["items"]} == {v1.id, v2.id}


# --- GET /api/submissions/{id} and history -------------------------------------------------


async def test_reading_a_submission_logs_non_self_reads(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"], body="Body text.")

    own = await (await authed_client("student")).get(f"/api/submissions/{sub.id}")
    taught = await (await authed_client("faculty")).get(f"/api/submissions/{sub.id}")
    other = await (await authed_client("faculty", person="chen")).get(f"/api/submissions/{sub.id}")
    missing = await (await authed_client("student")).get(f"/api/submissions/{new_id()}")

    assert own.status_code == 200 and own.json()["body_md"] == "Body text."
    assert taught.status_code == 200
    assert other.status_code == 403 and missing.status_code == 404
    entries = app.state.access_log.entries
    assert [(e.actor_id, e.resource, e.resource_id) for e in entries] == [
        (ids["faculty"], "submission", sub.id)]


async def test_reading_history_logs_non_self_reads(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])

    own = await (await authed_client("student")).get(f"/api/submissions/{sub.id}/history")
    taught = await (await authed_client("faculty")).get(f"/api/submissions/{sub.id}/history")

    assert own.status_code == 200 and taught.status_code == 200
    entries = app.state.access_log.entries
    assert [(e.actor_id, e.resource, e.resource_id) for e in entries] == [
        (ids["faculty"], "submission", sub.id)]


async def test_history_shows_the_learner_only_released_scores(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    v1 = store.add_submission(cs, ids["student"])
    v2 = store.add_submission(cs, ids["student"], parent=v1)
    store.score(v1, "evidence", 2, released=True)
    store.score(v2, "evidence", 3, released=True)
    store.score(v2, "thesis", 4)

    learner = (await (await authed_client("student")).get(
        f"/api/submissions/{v1.id}/history")).json()
    staff = (await (await authed_client("faculty")).get(
        f"/api/submissions/{v2.id}/history")).json()

    assert [v["submission"]["id"] for v in learner["versions"]] == [v1.id, v2.id]
    assert learner["versions"][1]["criteria"] == [{
        "criterion_id": store.criterion(cs, "evidence").criterion_id,
        "criterion_key": "evidence", "score": 3, "delta": 1}]
    assert {c["criterion_key"] for c in staff["versions"][1]["criteria"]} == {
        "evidence", "thesis"}
    assert learner["versions"][1]["submission"]["feedback_status"] == "released"


# --- GET /api/feedback ---------------------------------------------------------------------


async def test_the_learner_never_sees_unreleased_feedback(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    store.score(sub, "evidence", 2)

    learner = (await (await authed_client("student")).get(f"/api/feedback/{sub.id}")).json()
    staff = (await (await authed_client("faculty")).get(f"/api/feedback/{sub.id}")).json()

    assert (learner["status"], learner["criteria"]) == ("awaiting_release", [])
    assert learner["release_mode"] == "instructor_release"
    assert [c["criterion_key"] for c in staff["criteria"]] == ["evidence"]
    assert staff["student_name"] == "Emma Smith"


async def test_released_feedback_reaches_the_learner_with_their_practice_link(
        app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    store.score(sub, "evidence", 2, released=True, next_step="Cite a source.")
    store.score(sub, "thesis", 3)
    evidence = store.criterion(cs, "evidence").criterion_id
    store.practice[(ids["student"], evidence)] = "practice-1"

    learner = (await (await authed_client("student")).get(f"/api/feedback/{sub.id}")).json()
    staff = (await (await authed_client("faculty")).get(f"/api/feedback/{sub.id}")).json()

    assert learner["status"] == "released"
    assert [(c["criterion_key"], c["ai_score"], c["next_step"]) for c in learner["criteria"]] \
        == [("evidence", 2, "Cite a source.")]
    assert learner["practice_set_ai_action_id"] == "practice-1"
    assert staff["practice_set_ai_action_id"] is None


async def test_scores_are_hidden_from_the_learner_when_the_course_says_so(
        app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    store.settings[(CS101.course_id, "feedback.show_scores_on_drafts")] = False
    sub = store.add_submission(cs, ids["student"])
    store.score(sub, "evidence", 2, released=True)

    learner = (await (await authed_client("student")).get(f"/api/feedback/{sub.id}")).json()
    staff = (await (await authed_client("faculty")).get(f"/api/feedback/{sub.id}")).json()

    assert learner["criteria"][0]["ai_score"] is None
    assert staff["criteria"][0]["ai_score"] == 2


async def test_feedback_of_others_is_refused(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])

    for role, person in (("student", "noah"), ("faculty", "chen"), ("advisor", None),
                         ("admin", None)):
        client = await authed_client(role, person=person)
        assert (await client.get(f"/api/feedback/{sub.id}")).status_code == 403, role


# --- queue and release ---------------------------------------------------------------------


async def test_the_queue_lists_held_feedback_in_taught_courses(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    math = store.add_assignment(MATH201.course_id)
    held = store.add_submission(cs, ids["student"])
    store.score(held, "evidence", 2)
    released = store.add_submission(cs, ids["noah"])
    store.score(released, "evidence", 3, released=True)
    elsewhere = store.add_submission(math, ids["student"])
    store.score(elsewhere, "evidence", 2)
    faculty = await authed_client("faculty")

    queue = (await faculty.get("/api/feedback/queue")).json()

    assert [i["submission_id"] for i in queue["items"]] == [held.id]
    assert queue["items"][0]["status"] == "awaiting_release"
    assert (await faculty.get("/api/feedback/queue",
                              params={"course_id": MATH201.course_id})).status_code == 403
    assert (await (await authed_client("student")).get(
        "/api/feedback/queue")).status_code == 403


async def test_release_passes_changed_edits_and_the_reviewer(app, store, tools, authed_client,
                                                             ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    action = store.score(sub, "evidence", 2, next_step="Cite.")
    store.score(sub, "thesis", 3, action=action)
    evidence = store.criterion(cs, "evidence").criterion_id
    thesis = store.criterion(cs, "thesis").criterion_id

    def release(args):
        for cid in args["criterion_ids"]:
            if args["decision"] == "release":
                store.scores[(sub.id, cid)]["released_at"] = store.submissions[
                    sub.id].submitted_at
            else:
                store.decide(action, cid, "rejected")
        return {"submission_id": sub.id, "decision": args["decision"]}

    tools.replies["assessments.release_feedback"] = release
    faculty = await authed_client("faculty")

    resp = await faculty.post(f"/api/feedback/{sub.id}/release", json={
        "action": "release", "reason": "Adjusted.",
        "edits": [{"criterion_id": evidence, "score": 3, "next_step": "Cite."},
                  {"criterion_id": thesis, "suppress": True}]})
    await _drain(app)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "released"
    calls = tools.calls_to("assessments.release_feedback")
    assert calls[0] == {"submission_id": sub.id, "reviewer_id": ids["faculty"],
                        "reason": "Adjusted.", "decision": "release",
                        "criterion_ids": [evidence],
                        "edits": [{"criterion_id": evidence, "ai_score": 3}]}
    assert calls[1]["decision"] == "suppress" and calls[1]["criterion_ids"] == [thesis]
    assert tools.calls_to("assessments.weaknesses")[0]["student_id"] == ids["student"]
    again = await faculty.post(f"/api/feedback/{sub.id}/release", json={"action": "release"})
    assert again.status_code == 409


async def test_release_refusals(app, store, tools, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    pending = store.add_submission(cs, ids["student"])
    held = store.add_submission(cs, ids["noah"])
    store.score(held, "evidence", 2)
    faculty = await authed_client("faculty")

    def post(sub, **body):
        return faculty.post(f"/api/feedback/{sub.id}/release",
                            json={"action": "release", **body})

    assert (await post(pending)).status_code == 409
    assert (await post(held, edits=[{"criterion_id": new_id()}])).status_code == 422
    evidence = store.criterion(cs, "evidence").criterion_id
    assert (await post(held, edits=[{"criterion_id": evidence, "score": 9}])).status_code == 422
    tools.replies["assessments.release_feedback"] = {"error": "x", "code": "conflict"}
    assert (await post(held)).status_code == 409
    assert (await (await authed_client("student")).post(
        f"/api/feedback/{held.id}/release", json={"action": "release"})).status_code == 403
    assert (await (await authed_client("faculty", person="chen")).post(
        f"/api/feedback/{held.id}/release", json={"action": "release"})).status_code == 403
    store.settings[(CS101.course_id, "feedback.release_mode")] = "auto"
    assert (await post(held)).status_code == 409


# --- improvement ---------------------------------------------------------------------------

RAW = {"course_id": CS101.course_id,
       "criteria": [{"criterion_id": "k1", "key": "evidence", "description": "Evidence"}],
       "students": [{"student_id": "s", "trajectories": [
           {"criterion_id": "k1", "points": [{"submission_id": "a", "version": 1,
                                              "status": "draft", "score": 2, "at": "t"}],
            "delta": None, "flag": None}]}],
       "aggregate": [{"criterion_id": "k1", "n_students": 1, "mean_delta": None,
                      "flag_counts": {}}]}


async def test_improvement_scopes_by_role(app, auth_world, tools, authed_client, ids):
    def reply(args):
        student = args.get("student_id") or ids["student"]
        return {**RAW, "students": [{**RAW["students"][0], "student_id": student}]}

    tools.replies["assessments.get_improvement"] = reply
    url = f"/api/improvement/{CS101.course_id}"

    own = (await (await authed_client("student")).get(
        url, params={"student_id": ids["noah"]})).json()
    assert tools.calls_to("assessments.get_improvement")[-1] == {
        "course_id": CS101.course_id, "requester_id": ids["student"],
        "student_id": ids["student"]}
    assert [s["student_id"] for s in own["students"]] == [ids["student"]]
    assert "aggregate" not in own

    faculty = (await (await authed_client("faculty")).get(url)).json()
    assert faculty["students"][0]["display_name"] == "Emma Smith"
    assert faculty["criteria"][0]["description"] == "Evidence"

    advisor = (await (await authed_client("advisor")).get(url)).json()
    assert advisor["students"][0]["trajectories"][0]["points"] == []

    admin = (await (await authed_client("admin")).get(url)).json()
    assert admin["students"] == [] and admin["aggregate"][0]["n_students"] == 1

    auth_world.directory.programs[ids["program_lead"]] = frozenset({MATH201.course_id})
    lead = await authed_client("program_lead")
    assert (await lead.get(url)).status_code == 403
    tools.replies["assessments.get_improvement"] = RAW
    lead_view = (await lead.get(f"/api/improvement/{MATH201.course_id}")).json()
    assert lead_view["students"] == []


async def test_improvement_refusals(app, tools, authed_client, ids):
    chen = await authed_client("faculty", person="chen")
    assert (await chen.get(f"/api/improvement/{CS101.course_id}")).status_code == 403
    assert (await chen.get(f"/api/improvement/{new_id()}")).status_code == 404
    advisor = await authed_client("advisor")
    assert (await advisor.get(f"/api/improvement/{CS101.course_id}",
                              params={"student_id": ids["noah"]})).status_code == 403
    assert (await (await authed_client("student", person="noah")).get(
        f"/api/improvement/{CS101.course_id}")).status_code == 403
    tools.replies["assessments.get_improvement"] = {"error": "no", "code": "forbidden"}
    faculty = await authed_client("faculty")
    assert (await faculty.get(f"/api/improvement/{CS101.course_id}")).status_code == 403


def _release(store: InMemoryFormativeStore, sub: Any, *keys: str) -> None:
    for key in keys:
        cid = store.criterion(store.assignments[sub.assignment_id], key).criterion_id
        store.scores[(sub.id, cid)]["released_at"] = T0


async def test_history_gives_the_advisor_the_learner_view(app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    store.score(sub, "evidence", 2)
    thesis_action = store.score(sub, "thesis", 3)
    advisor = await authed_client("advisor")

    before = (await advisor.get(f"/api/submissions/{sub.id}/history")).json()
    _release(store, sub, "evidence", "thesis")
    store.decide(thesis_action, store.criterion(cs, "thesis").criterion_id, "rejected")
    after = (await advisor.get(f"/api/submissions/{sub.id}/history")).json()
    staff = (await (await authed_client("faculty")).get(
        f"/api/submissions/{sub.id}/history")).json()

    assert before["versions"][0]["criteria"] == []
    assert [(c["criterion_key"], c["score"]) for c in after["versions"][0]["criteria"]] == [
        ("evidence", 2)]
    assert {c["criterion_key"] for c in staff["versions"][0]["criteria"]} == {
        "evidence", "thesis"}


async def test_history_hides_draft_scores_from_the_advisor_when_the_course_says_so(
        app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    store.settings[(CS101.course_id, "feedback.show_scores_on_drafts")] = False
    sub = store.add_submission(cs, ids["student"])
    store.score(sub, "evidence", 2, released=True)

    advisor = (await (await authed_client("advisor")).get(
        f"/api/submissions/{sub.id}/history")).json()

    assert [(c["criterion_key"], c["score"]) for c in advisor["versions"][0]["criteria"]] == [
        ("evidence", None)]


async def test_history_gives_an_admin_the_learner_view_of_draft_versions(
        app, store, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    store.score(sub, "evidence", 2, released=True)
    store.score(sub, "thesis", 3)

    admin = (await (await authed_client("admin")).get(
        f"/api/submissions/{sub.id}/history")).json()

    assert [(c["criterion_key"], c["score"]) for c in admin["versions"][0]["criteria"]] == [
        ("evidence", 2)]


# --- failed feedback runs and retry --------------------------------------------------------


async def _submit_draft(app, store, tools, client, assignment) -> str:
    def submit(args):
        row = store.add_submission(store.assignments[args["assignment_node"]],
                                   args["person_id"], body=args["body_md"])
        return {"submission_id": row.id, "version": 1, "status": "draft"}

    tools.replies["assessments.submit"] = submit
    resp = await client.post("/api/submissions", json={
        "assignment_id": assignment.id, "status": "draft", "body_md": "My essay."})
    assert resp.status_code == 201, resp.text
    await _drain(app)
    return str(resp.json()["id"])


async def test_a_run_that_saves_nothing_is_failed_and_the_learner_can_retry(
        app, store, tools, stub_runner, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    student = await authed_client("student")
    faculty = await authed_client("faculty")
    sid = await _submit_draft(app, store, tools, student, cs)

    failed = (await student.get(f"/api/feedback/{sid}")).json()
    listed = (await student.get(f"/api/submissions/{sid}")).json()
    release = await faculty.post(f"/api/feedback/{sid}/release", json={"action": "release"})
    retry = await student.post(f"/api/feedback/{sid}/retry")
    status_after_retry = retry.json()["status"]
    await _drain(app)

    assert (failed["status"], listed["feedback_status"]) == ("failed", "failed")
    assert store.outputs[store.failures[sid][0]]["reason"] == "nothing_saved"
    assert release.status_code == 409
    assert (retry.status_code, status_after_retry) == (202, "pending")
    assert store.dismissed == {store.failures[sid][0]: ids["student"]}
    assert [c["agent"] for c in stub_runner.calls] == ["feedback", "feedback"]
    assert len(store.failures[sid]) == 2


async def test_an_agent_that_raises_leaves_a_failed_run(
        app, store, tools, stub_runner, authed_client, monkeypatch):
    async def boom(agent_name, inputs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(stub_runner, "run", boom)
    cs = store.add_assignment(CS101.course_id)
    student = await authed_client("student")
    sid = await _submit_draft(app, store, tools, student, cs)

    assert (await student.get(f"/api/feedback/{sid}")).json()["status"] == "failed"
    assert store.outputs[store.failures[sid][0]]["reason"] == "agent_error"


async def test_faculty_of_the_course_can_retry(app, store, tools, stub_runner, authed_client,
                                               ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    failure = await store.record_feedback_failure(sub, "agent_error")

    resp = await (await authed_client("faculty")).post(f"/api/feedback/{sub.id}/retry")
    await _drain(app)

    assert resp.status_code == 202, resp.text
    assert store.dismissed == {failure: ids["faculty"]}


async def test_retry_refusals(app, store, tools, stub_runner, authed_client, ids):
    cs = store.add_assignment(CS101.course_id)
    sub = store.add_submission(cs, ids["student"])
    await store.record_feedback_failure(sub, "agent_error")
    pending = store.add_submission(cs, ids["student"])

    for role, person in (("student", "noah"), ("faculty", "chen"), ("advisor", None),
                         ("admin", None)):
        client = await authed_client(role, person=person)
        assert (await client.post(f"/api/feedback/{sub.id}/retry")).status_code == 403, role
    student = await authed_client("student")
    assert (await student.post(f"/api/feedback/{pending.id}/retry")).status_code == 409
    assert (await student.post(f"/api/feedback/{new_id()}/retry")).status_code == 404
    assert store.dismissed == {}
