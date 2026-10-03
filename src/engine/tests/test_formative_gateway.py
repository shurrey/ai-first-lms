"""The gateway's arg_filter hook and object scope for the submission-keyed formative tools."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from engine.guardrails.gateway import BackgroundFeedback, GatewayContext
from engine.tests.auth_fakes import CS101, ENG102, AuthWorld, build_auth_world
from engine.tests.test_object_scope import Rig

SAVE = "assessments.save_criterion_feedback"
ARGS = {"submission_id": "sub-emma", "criteria": [
    {"criterion_id": "c1", "ai_score": 2, "ai_rationale": "r", "next_step": "n",
     "ai_evidence_spans": [{"quote": "essay"}, {"quote": "not there"}]}]}


# The background run started for Emma's CS 101 draft.
EMMA_RUN = BackgroundFeedback("sub-emma", "essay-cs")


@pytest.fixture
def world() -> AuthWorld:
    return build_auth_world()


def _keep_first_span(ctx: GatewayContext, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    criteria = [{**c, "ai_evidence_spans": c["ai_evidence_spans"][:1]}
                for c in args["criteria"]]
    return {**args, "criteria": criteria}


async def test_the_filter_rewrites_what_executes(world):
    rig = Rig(world)
    ctx = replace(rig.ctx("student"), arg_filter=_keep_first_span, background_feedback=EMMA_RUN)

    result = await rig.gateway.invoke(ctx, "feedback", SAVE, ARGS)

    assert result.success, result.text
    [sent] = rig.mcp.calls_to(SAVE)
    assert sent["criteria"][0]["ai_evidence_spans"] == [{"quote": "essay"}]


async def test_a_filter_may_not_change_which_record_the_call_names(world):
    rig = Rig(world)

    def retarget(ctx, tool, args):
        return {**args, "submission_id": "sub-noah"}

    result = await rig.gateway.invoke(
        replace(rig.ctx("student"), arg_filter=retarget, background_feedback=EMMA_RUN),
        "feedback", SAVE, ARGS)

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls_to(SAVE) == []


async def test_saving_feedback_on_another_learners_submission_is_denied(world):
    rig = Rig(world)

    result = await rig.gateway.invoke(
        replace(rig.ctx("noah", "student"), background_feedback=EMMA_RUN), "feedback", SAVE, ARGS)

    assert result.outcome == "denied_scope"
    assert rig.mcp.calls_to(SAVE) == []


async def test_a_learner_cannot_save_feedback_from_a_chat_turn(world):
    rig = Rig(world)

    result = await rig.invoke("student", "feedback", SAVE, ARGS)

    assert result.outcome == "denied_permission"
    assert rig.mcp.calls_to(SAVE) == []


@pytest.mark.parametrize("tool,args", [
    ("assessments.get_submission", {"submission_id": "sub-emma"}),
    ("assessments.get_rubric", {"rubric_id": "r1"}),
    (SAVE, ARGS),
])
@pytest.mark.parametrize("role", ["student", "faculty"])
async def test_the_feedback_agent_cannot_run_in_a_chat_turn(world, tool, args, role):
    rig = Rig(world, {"assessments.get_rubric": {"criteria": []}})

    result = await rig.invoke("faculty" if role == "faculty" else "student", "feedback",
                              tool, args, role=role)

    assert result.outcome == "denied_permission"
    assert rig.mcp.calls_to(tool) == []


async def test_a_feedback_run_reads_and_saves_only_the_submission_it_reviews(world):
    rig = Rig(world, {"assessments.list_submission_history": {"submissions": []}})
    run = replace(rig.ctx("student"), background_feedback=EMMA_RUN)
    other = {**ARGS, "submission_id": "sub-emma-math"}

    own_read = await rig.gateway.invoke(run, "feedback", "assessments.get_submission",
                                        {"submission_id": "sub-emma"})
    other_read = await rig.gateway.invoke(run, "feedback", "assessments.get_submission",
                                          {"submission_id": "sub-emma-math"})
    other_save = await rig.gateway.invoke(run, "feedback", SAVE, other)
    own_history = await rig.gateway.invoke(
        run, "feedback", "assessments.list_submission_history",
        {"assignment_node": "essay-cs", "course_id": CS101.course_id})
    other_history = await rig.gateway.invoke(
        run, "feedback", "assessments.list_submission_history",
        {"course_id": CS101.course_id})

    assert own_read.success and own_history.success
    assert other_read.outcome == other_save.outcome == other_history.outcome == "denied_scope"
    assert rig.mcp.calls_to(SAVE) == []
    assert len(rig.mcp.calls_to("assessments.list_submission_history")) == 1



def _course_rig(world: AuthWorld) -> Rig:
    rig = Rig(world, {"content.generate_practice": {"practice_set_id": "p1"},
                      "assessments.propose_alignment": {"proposal": None},
                      "graph.subgraph_for_outcomes": {"nodes": [], "edges": []},
                      "assessments.grading_status": {"assignments": []}})
    rig.objects.criteria.update({"crit-cs": CS101.course_id, "crit-eng": ENG102.course_id})
    rig.objects.nodes.update({"essay-cs": CS101.course_id, "essay-eng": ENG102.course_id,
                              "out-cs": CS101.course_id, "out-eng": ENG102.course_id})
    return rig


@pytest.mark.parametrize("agent,tool,inside,outside", [
    ("content_generator", "content.generate_practice",
     {"criterion_id": "crit-cs"}, {"criterion_id": "crit-eng"}),
    ("course_architect", "assessments.propose_alignment",
     {"assignment_node": "essay-cs"}, {"assignment_node": "essay-eng"}),
    ("course_architect", "graph.subgraph_for_outcomes",
     {"outcome_ids": ["out-cs"]}, {"outcome_ids": ["out-cs", "out-eng"]}),
])
async def test_course_keyed_formative_ids_must_be_in_the_callers_courses(
        world, agent, tool, inside, outside):
    rig = _course_rig(world)
    extra = ({"student_id": world.people["student"].id, "count": 3}
             if tool == "content.generate_practice" else {})

    allowed = await rig.invoke("faculty", agent, tool, {**inside, **extra})
    refused = await rig.invoke("faculty", agent, tool, {**outside, **extra})
    unknown = await rig.invoke("faculty", agent, tool,
                               {**{k: "nope" if isinstance(v, str) else ["nope"]
                                   for k, v in inside.items()}, **extra})

    assert allowed.success, allowed.text
    assert refused.outcome == "denied_scope"
    assert unknown.outcome == "denied_scope"
    assert len(rig.mcp.calls_to(tool)) == 1


async def test_faculty_grading_status_must_name_a_course(world):
    rig = _course_rig(world)
    tool = "assessments.grading_status"

    unscoped = await rig.invoke("faculty", "grading_assistant", tool, {"assignment_id": "a1"})
    scoped = await rig.invoke("faculty", "grading_assistant", tool,
                              {"course_id": CS101.course_id})
    other = await rig.invoke("faculty", "grading_assistant", tool,
                             {"course_id": ENG102.course_id})

    assert unscoped.outcome == "denied_scope"
    assert scoped.success, scoped.text
    assert other.outcome == "denied_scope"
