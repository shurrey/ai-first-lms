"""Deterministic agent post-processors (engine/agents/post) and their runner wiring."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import engine.agents.runner as runner_mod
from engine.agents.post import (
    POST_PROCESSORS,
    ToolOutput,
    apply_artifact_post_processors,
    apply_post_processors,
)
from engine.agents.runner import ClaudeAgentRunner
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.tests.auth_fakes import CS101, auth_context, build_auth_world
from engine.tests.object_fakes import InMemoryObjectDirectory

RUBRIC = {
    "id": "rub-1",
    "title": "Rubric for Lab 3",
    "criteria": [
        {"name": "Correctness", "levels": [
            {"label": "Excellent", "points": 40}, {"label": "Poor", "points": 10}]},
        {"name": "Style", "levels": [
            {"label": "Excellent", "points": 30}, {"label": "Poor", "points": 7}]},
    ],
}
LONG_BODY = "def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n" * 2


def _submission(sid: str, body: str) -> ToolOutput:
    return ToolOutput("assessments.get_submission", {"submission_id": sid}, {
        "id": sid, "person_id": "p-1", "assignment_node": "n-1", "body_md": body,
        "attachments": None, "submitted_at": "2026-09-30T10:00:00+00:00",
    })


def _draft(sid: str, scores: dict[str, Any]) -> ToolOutput:
    return ToolOutput("assessments.draft_grade", {
        "submission_id": sid, "rubric_id": "rub-1", "scores": scores,
        "feedback": {}, "graded_by": "f-1",
    }, {"grade_id": f"grade-{sid}"})


def _rubric() -> ToolOutput:
    return ToolOutput("assessments.get_rubric", {"rubric_id": "rub-1"}, RUBRIC)


def _roster(students: int, staff: int = 1) -> ToolOutput:
    persons = [{"id": f"s-{i}", "display_name": f"Student {i}", "role": "student"}
               for i in range(students)]
    persons += [{"id": f"f-{i}", "display_name": f"Prof {i}", "role": "faculty"}
                for i in range(staff)]
    return ToolOutput("roster.list_by_course", {"course_id": CS101.course_id}, {"persons": persons})


def _query(*sizes: int) -> ToolOutput:
    return ToolOutput("analytics.query", {"metric": "evidence_count"}, {
        "rows": [{"value": 1.0, "sample_size": s, "dimension": f"d{i}"}
                 for i, s in enumerate(sizes)],
        "metadata": {"metric": "evidence_count"},
    })


def test_every_post_processor_agent_has_a_manifest():
    from engine.guardrails.registry import get_manifest_registry

    registry = get_manifest_registry()
    for agent in POST_PROCESSORS:
        assert registry.get_manifest(agent).name == agent


def test_agent_without_post_processors_gets_its_output_back_unchanged():
    output = {"response_markdown": "Hi"}

    assert apply_post_processors("tutor", output, [_query(3)]) is output


def test_caller_output_is_not_mutated():
    output = {"response_markdown": "Trends.", "caveats": []}

    result = apply_post_processors("engagement_analyst", output, [_query(12)])

    assert output == {"response_markdown": "Trends.", "caveats": []}
    assert result["caveats"] == ["Sample size is 12 — interpret with caution."]


# --- grading_assistant -----------------------------------------------------------------------


def test_grading_flags_short_submission_and_minimum_score_in_the_note():
    output = {"response_markdown": "I drafted grades for two submissions."}
    calls = [_rubric(), _submission("sub-short-1", "todo"), _submission("sub-long-22", LONG_BODY),
             _draft("sub-short-1", {"Correctness": 10, "Style": 20}),
             _draft("sub-long-22", {"Correctness": 40, "Style": 30})]

    result = apply_post_processors("grading_assistant", output, calls)

    note = result["response_markdown"].split("> **Note:** ", 1)[1]
    assert "submission sub-shor" in note
    assert "short_submission: body is under 50 characters" in note
    assert "boundary_score: Correctness at minimum" in note
    assert "sub-long" not in note


def test_grading_flags_structured_drafts_and_caps_confidence():
    output = {"drafts": [
        {"submission_id": "sub-1", "scores": {"Style": 7}, "confidence": 0.9},
        {"submission_id": "sub-2", "scores": {"Style": 30}, "confidence": 0.9},
    ]}

    result = apply_post_processors(
        "grading_assistant", output, [_rubric(), _submission("sub-2", LONG_BODY)])

    flagged, clean = result["drafts"]
    assert flagged["flags"] == ["boundary_score: Style at minimum"]
    assert flagged["confidence"] == 0.6
    assert "flags" not in clean
    assert clean["confidence"] == 0.9


def test_grading_explicit_min_points_and_object_scores():
    rubric = ToolOutput("assessments.get_rubric", {}, {"criteria": [
        {"id": "c1", "name": "Depth", "min_points": 2, "levels": [{"points": 0}]}]})

    result = apply_post_processors("grading_assistant", {"response_markdown": "x"},
                                   [rubric, _draft("sub-9", {"c1": {"points": 2}})])

    assert "boundary_score: c1 at minimum" in result["response_markdown"]


def test_grading_with_nothing_to_flag_leaves_output_alone():
    output = {"response_markdown": "Drafted."}

    result = apply_post_processors("grading_assistant", output, [
        _rubric(), _submission("sub-1", LONG_BODY), _draft("sub-1", {"Correctness": 30})])

    assert result == output


# --- early_alert -----------------------------------------------------------------------------


def test_early_alert_small_cohort_caveat_from_roster_students():
    output = {"response_markdown": "Three students look at risk.",
              "methodology_note": "Risk from login and grade trend."}

    result = apply_post_processors("early_alert", output, [_roster(12, staff=3)])

    assert result["methodology_note"].startswith(
        "Risk from login and grade trend. N=12 student(s) in scope. With 12 student(s)")
    assert "> **Note:** With 12 student(s), individual variation" in result["response_markdown"]


def test_early_alert_large_cohort_records_n_without_caveat():
    result = apply_post_processors("early_alert", {"response_markdown": "x"}, [_roster(40)])

    assert result["methodology_note"] == "N=40 student(s) in scope."
    assert result["response_markdown"] == "x"


def test_early_alert_falls_back_to_largest_analytics_sample():
    result = apply_post_processors("early_alert", {"response_markdown": "x"}, [_query(9, 4)])

    assert result["methodology_note"].startswith("N=9 student(s) in scope. With 9")


def test_early_alert_without_cohort_data_is_unchanged():
    output = {"response_markdown": "No data."}

    assert apply_post_processors("early_alert", output, [_query(0)]) == output


# --- engagement_analyst ----------------------------------------------------------------------


def test_engagement_caveat_uses_smallest_analysed_group():
    cohorts = ToolOutput("analytics.cohort_compare", {}, {"cohort_results": [
        {"cohort": "A", "value": 2.0, "sample_size": 45},
        {"cohort": "B", "value": 1.0, "sample_size": 18}]})
    output = {"response_markdown": "Cohort A is more engaged.", "caveats": ["Window is 14 days."]}

    result = apply_post_processors("engagement_analyst", output, [_query(60), cohorts])

    assert result["caveats"] == ["Window is 14 days.",
                                 "Sample size is 18 — interpret with caution."]
    assert result["response_markdown"].endswith(
        "> **Note:** Sample size is 18 — interpret with caution.")


def test_engagement_large_sample_has_no_caveat():
    output = {"response_markdown": "x"}

    assert apply_post_processors("engagement_analyst", output, [_query(30, 31)]) == output


def test_engagement_uses_roster_when_no_analytics_ran():
    result = apply_post_processors("engagement_analyst", {"response_markdown": "x"}, [_roster(8)])

    assert result["caveats"] == ["Sample size is 8 — interpret with caution."]


# --- accessibility ---------------------------------------------------------------------------


def test_accessibility_recounts_model_report_summary():
    output = {"proposals": [], "report": {
        "issues": [{"rule": "1.1.1", "severity": "error", "description": "alt"},
                   {"rule": "2.4.4", "severity": "warning", "description": "link"},
                   {"rule": "1.3.1", "severity": "error", "description": "heading"}],
        "summary": {"errors": 1, "warnings": 5, "passes": 4}}}

    result = apply_post_processors("accessibility", output, [])

    assert result["report"]["summary"] == {"errors": 2, "warnings": 1, "passes": 4}


def test_accessibility_builds_report_from_check_wcag_findings():
    wcag = ToolOutput("standards.check_wcag", {"content_id": "c-1"}, {
        "compliant": False, "level": "AA", "content_id": "c-1", "findings": [
            {"criterion": "1.1.1", "status": "fail", "details": "2 image(s) missing alt text"},
            {"criterion": "1.3.1", "status": "pass", "details": "Heading structure ok"},
            {"criterion": "1.4.3", "status": "not_applicable", "details": "n/a"}]})

    result = apply_post_processors("accessibility", {"response_markdown": "x"}, [wcag])

    assert result["report"] == {
        "issues": [{"rule": "1.1.1", "severity": "error",
                    "description": "2 image(s) missing alt text"}],
        "summary": {"errors": 1, "warnings": 0, "passes": 1},
    }


# --- assessment ------------------------------------------------------------------------------


def test_assessment_warns_on_bloom_outside_difficulty_range():
    calls = [ToolOutput("assessments.create_question", {
        "bank_id": "b", "type": "mcq", "stem": "s", "answer_key": "a",
        "bloom_level": bloom, "difficulty": difficulty}, {"question_id": f"q{i}"})
        for i, (bloom, difficulty) in enumerate(
            [("remember", "intro"), ("create", "intro"), ("evaluate", "mixed")])]

    result = apply_post_processors("assessment", {"response_markdown": "Quiz saved."}, calls)

    assert result["warnings"] == [
        "Question 2: Bloom level 'create' is outside the usual range for intro difficulty "
        "(remember, understand)."]
    assert "Question 2" in result["response_markdown"]


def test_assessment_prefers_structured_questions():
    output = {"questions": [{"bloom_level": "Remember", "difficulty": "advanced"}],
              "warnings": ["Question 1: no graph node alignment found."]}

    result = apply_post_processors("assessment", output, [ToolOutput(
        "assessments.create_question", {"bloom_level": "create", "difficulty": "intro"}, {})])

    assert len(result["warnings"]) == 2
    assert "'remember' is outside the usual range for advanced" in result["warnings"][1]


# --- advising --------------------------------------------------------------------------------


def test_advising_flags_credit_overload_and_keeps_recommendations():
    output = {"audit": {}, "recommendations": [
        {"course_id": c, "credits": 4} for c in ("CS201", "CS210", "MATH220", "PHYS101")]}

    result = apply_post_processors("advising", output, [])

    assert len(result["recommendations"]) == 4
    assert result["risks"][0]["type"] == "credit_load"
    assert "16 credits" in result["risks"][0]["description"]


def test_advising_without_credits_is_unchanged():
    output = {"audit": {}, "recommendations": [{"course_id": "CS201"}]}

    assert apply_post_processors("advising", output, []) == output


# --- runner wiring ---------------------------------------------------------------------------


def _usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=10, output_tokens=5)


class _Client:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.messages = self

    async def create(self, **_: Any) -> SimpleNamespace:
        return self._responses.pop(0)


class _Executor:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        return json.dumps(self.result)


async def test_runner_applies_post_processors_to_live_output(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    world = build_auth_world()
    executor = _Executor({"id": "sub-1", "person_id": world.people["student"].id,
                          "body_md": "tbd", "submitted_at": "2026-09-30T10:00:00Z"})
    gateway = ToolGateway(executor, directory=world.directory,
                          objects=InMemoryObjectDirectory({"sub-1": CS101.course_id}))
    client = _Client([
        SimpleNamespace(stop_reason="tool_use", usage=_usage(), content=[SimpleNamespace(
            type="tool_use", id="tu1", name="assessments_get_submission",
            input={"submission_id": "sub-1"})]),
        SimpleNamespace(stop_reason="end_turn", usage=_usage(),
                        content=[SimpleNamespace(type="text", text="Draft ready.")]),
    ])
    ctx = GatewayContext(auth=auth_context(world, "faculty"), session_id="sess-1",
                         turn_id="turn-1", step_id="s1")

    result = await ClaudeAgentRunner(client=client, gateway=gateway).run(
        "grading_assistant", {"message": "grade it", "_tool_context": ctx})

    assert result["success"] is True
    assert result["output"]["response_markdown"].startswith("Draft ready.\n\n> **Note:**")
    assert "short_submission" in result["output"]["response_markdown"]
    assert "value" not in result["tool_calls"][0]


async def test_gateway_result_value_is_redacted_and_unwrapped_only_on_success():
    world = build_auth_world()
    ok = await ToolGateway(_Executor({"id": "t1", "content": "hi"}), directory=world.directory
                           ).invoke(GatewayContext(auth=auth_context(world, "student"),
                                                   session_id="sess-1"),
                                    "learning_analyst", "roster.get_session_transcript",
                                    {"session_id": "sess-1"})
    failed = await ToolGateway(_Executor({"error": "not found"}), directory=world.directory
                               ).invoke(GatewayContext(auth=auth_context(world, "student"),
                                                       session_id="sess-1"),
                                        "tutor", "content.search", {"query": "x"})

    assert ok.value == {"id": "t1", "content": "hi"}
    assert failed.outcome == "error"
    assert failed.value is None


def test_artifact_post_processors_recount_wcag_blocks_without_mutating_them():
    block = {"type": "wcag_report", "data": {
        "issues": [{"rule": "1.1.1", "severity": "error"}], "summary": {"errors": 5}}}
    other = {"type": "chart", "data": {"x_key": "x"}}

    [recounted, untouched] = apply_artifact_post_processors([block, other])

    assert recounted["data"]["summary"] == {"errors": 1, "warnings": 0, "passes": 0}
    assert block["data"]["summary"] == {"errors": 5}
    assert untouched is other
