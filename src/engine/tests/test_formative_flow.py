"""FormativeFlow with an in-memory store, a recording tool caller and a scripted agent runner."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from engine.formative.flow import (
    FEEDBACK_AGENT,
    PRACTICE_AGENT,
    RELEASE_TOOL,
    SAVE_TOOL,
    WEAKNESS_TOOL,
    FormativeFlow,
    ToolRefusedError,
)
from engine.formative.locks import KeyedLocks
from engine.guardrails.gateway import BackgroundFeedback, ToolGateway
from engine.provenance import ProvenanceTrail
from engine.tests.formative_fakes import T0, InMemoryFormativeStore, RecordingTools, new_id

COURSE = "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9"
BODY = "Evidence: a 2023 survey of teens. Claim: schools should act."


class ScriptedRunner:
    """Plays the feedback agent (saves through the context's arg filter, as the gateway
    would) and the practice agent (records a practice set) against the store."""

    def __init__(self, store: InMemoryFormativeStore, scores: dict[str, int],
                 spans: list[dict[str, Any]] | None = None, save: bool = True) -> None:
        self.store = store
        self.scores = scores
        self.spans = spans if spans is not None else [{"quote": "a 2023 survey"}]
        self.save = save
        self.runs: list[tuple[str, dict[str, Any]]] = []
        self.saved_args: list[dict[str, Any]] = []

    async def run(self, agent: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self.runs.append((agent, inputs))
        ctx = inputs["_tool_context"]
        if agent == FEEDBACK_AGENT and self.save:
            sub_id = inputs["message"].split("draft submission ")[1].split(" ")[0]
            sub = self.store.submissions[sub_id]
            args = {"submission_id": sub_id, "criteria": [
                {"criterion_id": self.store.criterion(
                    self.store.assignments[sub.assignment_id], k).criterion_id,
                 "ai_score": v, "ai_rationale": "why", "next_step": "next",
                 "ai_evidence_spans": list(self.spans)} for k, v in self.scores.items()]}
            trail = ProvenanceTrail(model="claude-test", prompt_sha256="abc")
            ctx = replace(ctx, provenance=trail)
            self.saved_args.append(ctx.arg_filter(ctx, SAVE_TOOL, args))
            action = new_id()
            for key, score in self.scores.items():
                self.store.score(sub, key, score, action=action)
        if agent == PRACTICE_AGENT:
            criterion = inputs["message"].split("criterion_id ")[1].split(";")[0]
            self.store.practice[(inputs["person_id"], criterion)] = new_id()
        return {"success": True, "output": {}}


def _flow(store, runner, tools) -> FormativeFlow:
    return FormativeFlow(store, gateway=ToolGateway(_unused), directory=None, locks=KeyedLocks(),
                         runner=runner, call_tool=tools)


async def _unused(tool: str, args: dict[str, Any]) -> str:
    raise AssertionError(f"the scripted runner makes no gateway calls ({tool})")


@pytest.fixture
def store() -> InMemoryFormativeStore:
    return InMemoryFormativeStore(names={"emma": "Emma"})


def _weak(store, assignment, key: str = "evidence"):
    criterion = store.criterion(assignment, key)
    return {WEAKNESS_TOOL: {"weaknesses": [{"criterion_id": criterion.criterion_id,
                                             "key": key, "last_scores": [2, 2]}]}}


async def test_auto_release_runs_feedback_releases_and_generates_practice(store):
    assignment = store.add_assignment(COURSE)
    store.settings[(COURSE, "feedback.release_mode")] = "auto"
    store.settings[(COURSE, "feedback.weakness_window")] = 4
    sub = store.add_submission(assignment, "emma", body=BODY)
    runner = ScriptedRunner(store, {"thesis": 3, "evidence": 2})
    tools = RecordingTools(_weak(store, assignment))

    await _flow(store, runner, tools).submitted(sub.id)

    assert [agent for agent, _ in runner.runs] == [FEEDBACK_AGENT, PRACTICE_AGENT]
    feedback_inputs = runner.runs[0][1]
    assert feedback_inputs["persona"] == "student" and feedback_inputs["person_id"] == "emma"
    learner = feedback_inputs["_tool_context"].auth
    assert learner.active_role == "student" and learner.person_id == "emma"
    assert [e.course_id for e in learner.enrollments] == [COURSE]
    assert feedback_inputs["_tool_context"].background_feedback == BackgroundFeedback(
        sub.id, assignment.id)
    assert runner.runs[1][1]["_tool_context"].background_feedback is None
    assert tools.calls_to(RELEASE_TOOL) == [{"submission_id": sub.id, "decision": "release"}]
    assert tools.calls_to(WEAKNESS_TOOL) == [{"student_id": "emma", "course_id": COURSE,
                                              "window": 4}]
    evidence = store.criterion(assignment, "evidence").criterion_id
    assert (("emma", evidence)) in store.practice


async def test_the_save_keeps_only_verbatim_spans_and_the_action_records_the_rest(store):
    assignment = store.add_assignment(COURSE)
    sub = store.add_submission(assignment, "emma", body=BODY)
    runner = ScriptedRunner(store, {"evidence": 2},
                            spans=[{"quote": "a 2023 survey"}, {"quote": "a 2024 study"}])

    await _flow(store, runner, RecordingTools()).submitted(sub.id)

    saved = runner.saved_args[0]["criteria"][0]["ai_evidence_spans"]
    assert saved == [{"quote": "a 2023 survey", "start": 10, "end": 23}]
    evidence = store.criterion(assignment, "evidence").criterion_id
    [note] = store.annotations
    assert (note["model"], note["prompt_sha256"]) == ("claude-test", "abc")
    assert note["output"] == {"dropped_spans": {
        evidence: [{"quote": "a 2024 study", "reason": "not_verbatim"}]}}
    assert {"type": "submission", "id": sub.id, "version": 1} in note["sources"]


async def test_instructor_release_holds_feedback_and_skips_weaknesses(store):
    assignment = store.add_assignment(COURSE)
    sub = store.add_submission(assignment, "emma", body=BODY)
    runner = ScriptedRunner(store, {"evidence": 2})
    tools = RecordingTools(_weak(store, assignment))

    await _flow(store, runner, tools).submitted(sub.id)

    assert [agent for agent, _ in runner.runs] == [FEEDBACK_AGENT]
    assert tools.calls == []


async def test_finals_and_assignments_without_a_rubric_get_no_feedback(store):
    assignment = store.add_assignment(COURSE)
    final = store.add_submission(assignment, "emma", status="final")
    bare = store.add_assignment(COURSE, keys=())
    draft = store.add_submission(bare, "emma")
    runner = ScriptedRunner(store, {})

    await _flow(store, runner, RecordingTools()).submitted(final.id)
    await _flow(store, runner, RecordingTools()).submitted(draft.id)
    await _flow(store, runner, RecordingTools()).submitted(new_id())

    assert runner.runs == []


async def test_nothing_is_released_when_the_agent_saved_nothing(store):
    assignment = store.add_assignment(COURSE)
    store.settings[(COURSE, "feedback.release_mode")] = "auto"
    sub = store.add_submission(assignment, "emma")
    tools = RecordingTools()

    await _flow(store, ScriptedRunner(store, {"evidence": 2}, save=False), tools).submitted(
        sub.id)

    assert tools.calls == [] and store.annotations == []


async def test_a_failed_auto_release_stops_before_weakness_detection(store):
    assignment = store.add_assignment(COURSE)
    store.settings[(COURSE, "feedback.release_mode")] = "auto"
    sub = store.add_submission(assignment, "emma", body=BODY)
    tools = RecordingTools({RELEASE_TOOL: {"error": "boom"}})

    await _flow(store, ScriptedRunner(store, {"evidence": 2}), tools).submitted(sub.id)

    assert [name for name, _ in tools.calls] == [RELEASE_TOOL]
    [failure] = store.failures[sub.id]
    assert store.outputs[failure]["reason"] == "release_failed"


async def test_a_retry_after_a_refused_auto_release_releases_the_saved_feedback(store):
    assignment = store.add_assignment(COURSE)
    store.settings[(COURSE, "feedback.release_mode")] = "auto"
    sub = store.add_submission(assignment, "emma", body=BODY)
    runner = ScriptedRunner(store, {"evidence": 2})
    await _flow(store, runner, RecordingTools({RELEASE_TOOL: {"error": "boom"}})).submitted(
        sub.id)
    await store.dismiss_failures(store.failures[sub.id], "emma")

    def release(args):
        for (sid, _), score in store.scores.items():
            if sid == args["submission_id"]:
                score["released_at"] = T0
        return {"ok": True}

    tools = RecordingTools({RELEASE_TOOL: release, **_weak(store, assignment)})
    await _flow(store, runner, tools).submitted(sub.id)

    assert [agent for agent, _ in runner.runs] == [FEEDBACK_AGENT, PRACTICE_AGENT]
    assert tools.calls_to(RELEASE_TOOL) == [{"submission_id": sub.id, "decision": "release"}]
    assert len(store.failures[sub.id]) == 1 and len(store.annotations) == 1


async def test_practice_is_not_generated_twice_for_one_criterion(store):
    assignment = store.add_assignment(COURSE)
    sub = store.add_submission(assignment, "emma")
    evidence = store.criterion(assignment, "evidence").criterion_id
    store.practice[("emma", evidence)] = "existing"
    runner = ScriptedRunner(store, {})

    await _flow(store, runner, RecordingTools(_weak(store, assignment))).feedback_visible(
        sub.id)

    assert runner.runs == []


async def test_review_releases_with_edits_and_suppresses_the_rest(store):
    assignment = store.add_assignment(COURSE)
    sub = store.add_submission(assignment, "emma")
    action = store.score(sub, "thesis", 3)
    store.score(sub, "evidence", 2, action=action)
    pending = (await store.criteria([sub.id]))[sub.id]
    thesis, evidence = (store.criterion(assignment, k).criterion_id
                        for k in ("thesis", "evidence"))
    tools = RecordingTools()

    await _flow(store, ScriptedRunner(store, {}), tools).review(
        sub, pending=pending, reviewer_id="watson", action="release",
        edits={evidence: {"ai_score": 3}}, suppress=frozenset({thesis}), reason="ok")

    assert tools.calls_to(RELEASE_TOOL) == [
        {"submission_id": sub.id, "reviewer_id": "watson", "reason": "ok",
         "decision": "release", "criterion_ids": [evidence],
         "edits": [{"criterion_id": evidence, "ai_score": 3}]},
        {"submission_id": sub.id, "reviewer_id": "watson", "reason": "ok",
         "decision": "suppress", "criterion_ids": [thesis]},
    ]


async def test_review_suppress_all_and_refusals(store):
    assignment = store.add_assignment(COURSE)
    sub = store.add_submission(assignment, "emma")
    store.score(sub, "thesis", 3)
    pending = (await store.criteria([sub.id]))[sub.id][:1]
    tools = RecordingTools({RELEASE_TOOL: {"error": "already", "code": "conflict"}})

    with pytest.raises(ToolRefusedError) as refused:
        await _flow(store, ScriptedRunner(store, {}), tools).review(
            sub, pending=pending, reviewer_id="watson", action="suppress", edits={},
            suppress=frozenset(), reason=None)

    assert refused.value.code == "conflict"
    assert tools.calls_to(RELEASE_TOOL)[0]["decision"] == "suppress"
