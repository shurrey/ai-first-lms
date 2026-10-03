"""Tests for artifact extraction (engine.agents.artifacts) and its path to the final event."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import engine.agents.runner as runner_mod
from engine.agents.artifacts import (
    AGENT_ARTIFACT_TYPES,
    ARTIFACT_TYPES,
    artifact_instruction,
    collect_artifacts,
    output_artifacts,
    split_artifact_blocks,
    tool_artifacts,
)
from engine.agents.post import ToolOutput, apply_post_processors
from engine.agents.runner import ClaudeAgentRunner
from engine.graph.dispatch import dispatch, set_agent_runner
from engine.graph.synthesize import synthesize
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.tests.auth_fakes import CS101, auth_context, build_auth_world
from engine.tests.object_fakes import InMemoryObjectDirectory

RUBRIC = {
    "id": "rub-1",
    "title": "Essay rubric",
    "criteria": [
        {"name": "Thesis", "levels": [
            {"label": "Strong", "points": 10}, {"label": "Weak", "points": 4}]},
        {"name": "Evidence", "levels": [
            {"label": "Strong", "points": 10}, {"label": "Weak", "points": 3}]},
    ],
}


def _draft_grade(sid: str = "sub-1") -> ToolOutput:
    return ToolOutput("assessments.draft_grade", {
        "submission_id": sid, "rubric_id": "rub-1",
        "scores": {"Thesis": 10, "Evidence": {"points": 3}},
        "feedback": {"Thesis": "Clear."}, "holistic_md": "Good start.", "graded_by": "f-1",
    }, {"grade_id": f"grade-{sid}"})


def test_every_contract_type_is_reachable_and_agents_are_known():
    from engine.guardrails.registry import get_manifest_registry

    registry = get_manifest_registry()
    reachable = {t for types in AGENT_ARTIFACT_TYPES.values() for t in types}
    assert reachable == ARTIFACT_TYPES
    for agent in AGENT_ARTIFACT_TYPES:
        registry.get_manifest(agent)


def test_draft_grade_becomes_rubric_grades_with_selected_levels():
    calls = [ToolOutput("assessments.get_rubric", {"rubric_id": "rub-1"}, RUBRIC), _draft_grade()]

    [artifact] = tool_artifacts("grading_assistant", calls)

    assert artifact["type"] == "rubric_grades"
    data = artifact["data"]
    assert data["title"] == "Essay rubric"
    assert data["status"] == "draft"
    assert data["grade_id"] == "grade-sub-1"
    assert data["total_points"] == 13
    assert [c.get("selected_level") for c in data["criteria"]] == [0, 1]


def test_committed_grade_is_marked_committed():
    calls = [_draft_grade(), ToolOutput(
        "assessments.commit_grade", {"grade_id": "grade-sub-1"},
        {"committed": True, "committed_at": "2026-10-02T10:00:00Z"})]

    [artifact] = tool_artifacts("grading_assistant", calls)

    assert artifact["data"]["status"] == "committed"
    assert [c["name"] for c in artifact["data"]["criteria"]] == ["Thesis", "Evidence"]


def test_draft_message_and_send_become_one_sent_message():
    calls = [
        ToolOutput("communications.draft_message", {
            "author_id": "f-1", "channel": "announcement", "subject": "Midterm Monday",
            "body_md": "The midterm is on Monday.", "audience": '{"course_id": "cs101"}',
        }, {"draft_id": "d-1"}),
        ToolOutput("communications.send_message", {"draft_id": "d-1"},
                   {"sent_at": "2026-10-02T10:00:00Z", "recipient_count": 50}),
    ]

    [artifact] = tool_artifacts("communication", calls)

    assert artifact == {"type": "message", "data": {
        "body": "The midterm is on Monday.", "recipients": ["course_id: cs101"],
        "channel": "announcement", "draft_id": "d-1", "status": "sent",
        "subject": "Midterm Monday", "recipient_count": 50,
    }}


def test_created_questions_become_one_quiz():
    calls = [ToolOutput("assessments.create_question", {
        "bank_id": "b-1", "type": "mcq", "stem": f"Q{i}?", "options": ["a", "b"],
        "answer_key": {"correct": "a"},
    }, {"question_id": f"q-{i}"}) for i in range(3)]

    [artifact] = tool_artifacts("assessment", calls)

    assert artifact["type"] == "quiz"
    assert [q["question"] for q in artifact["data"]["questions"]] == ["Q0?", "Q1?", "Q2?"]
    assert artifact["data"]["questions"][0]["type"] == "multiple_choice"
    assert artifact["data"]["questions"][0]["correct_answer"] == "a"


def test_analytics_series_become_charts_for_the_engagement_analyst_only():
    calls = [
        ToolOutput("analytics.trend", {"metric": "engagement_count", "interval": "week"},
                   {"series": [{"x": "2026-09-01", "y": 4}, {"x": "2026-09-08", "y": 7}]}),
        ToolOutput("analytics.cohort_compare", {"metric": "avg_score"},
                   {"cohort_results": [{"cohort": {"label": "A"}, "value": 0.7,
                                        "sample_size": 12}]}),
        ToolOutput("analytics.query", {"metric": "avg_score"},
                   {"rows": [{"value": 0.5, "sample_size": 30}]}),
    ]

    charts = tool_artifacts("engagement_analyst", calls)

    assert [c["data"]["chart_type"] for c in charts] == ["line", "bar"]
    assert charts[0]["data"]["data"][1] == {"x": "2026-09-08", "engagement_count": 7}
    assert charts[1]["data"]["data"][0]["cohort"] == "A"
    assert tool_artifacts("early_alert", calls) == []


def test_degree_audit_totals_come_from_requirements():
    calls = [ToolOutput("sis.degree_audit", {"student_id": "s-1"}, {
        "program": "BS Computer Science",
        "requirements": [
            {"id": "r1", "name": "Core", "credits_required": 30, "credits_applied": 12,
             "satisfied": False},
            {"id": "r2", "name": "Gen Ed", "credits_required": 15, "credits_applied": 15,
             "satisfied": True},
        ],
        "satisfied": False, "remaining": 18, "projected_graduation": "Spring 2028",
    })]

    [artifact] = tool_artifacts("advising", calls)

    assert artifact["data"]["total_credits_required"] == 45
    assert artifact["data"]["total_credits_completed"] == 27
    assert artifact["data"]["requirements"][0]["name"] == "Core"


def test_saved_draft_becomes_content_draft():
    calls = [ToolOutput("content.save_draft", {
        "kind": "syllabus", "title": "Intro to Data Ethics", "body_md": "# Week 1",
        "author_id": "f-1"}, {"draft_id": "c-1"})]

    assert tool_artifacts("course_architect", calls) == [{"type": "content_draft", "data": {
        "title": "Intro to Data Ethics", "kind": "syllabus", "body_md": "# Week 1",
        "draft_id": "c-1"}}]


def test_prerequisites_become_a_learning_path():
    calls = [ToolOutput("graph.prerequisites", {"node_id": "n-goal"}, {"prerequisites": [
        {"id": "n-1", "title": "Thesis statements", "kind": "concept", "satisfied": True},
        {"id": "n-2", "title": "Paragraph structure", "kind": "concept", "satisfied": False},
    ]})]

    [artifact] = tool_artifacts("tutor", calls)

    assert artifact["data"]["recommended_next"] == ["n-2"]
    assert {e["to"] for e in artifact["data"]["edges"]} == {"n-goal"}


def test_structured_keys_map_per_agent():
    assert output_artifacts("communication", {"drafts": [{"body": "hi", "recipients": []}]}) == [
        {"type": "message", "data": {"body": "hi", "recipients": []}}]
    assert output_artifacts("grading_assistant", {"drafts": [{"submission_id": "s"}]})[0][
        "type"] == "rubric_grades"
    assert output_artifacts("early_alert", {"at_risk": [{"name": "A"}]}) == [
        {"type": "risk_list", "data": {"students": [{"name": "A"}]}}]
    assert output_artifacts("tutor", {"questions": [{"stem": "x"}]}) == []


def test_artifact_block_is_parsed_and_removed_from_the_reply():
    text = (
        "Two students need attention.\n\n"
        "```artifact risk_list\n"
        '{"students": [{"name": "Ana", "risk_score": 0.8, "factors": ["missed labs"]}]}\n'
        "```\n"
    )

    reply, blocks = split_artifact_blocks("early_alert", text)

    assert reply == "Two students need attention."
    assert blocks == [{"type": "risk_list", "data": {
        "students": [{"name": "Ana", "risk_score": 0.8, "factors": ["missed labs"]}]}}]


def test_disallowed_or_malformed_blocks_are_dropped_and_logged(caplog: pytest.LogCaptureFixture):
    text = "Answer.\n```artifact quiz\n{}\n```\n```artifact risk_list\nnot json\n```"

    reply, blocks = split_artifact_blocks("early_alert", text)

    assert reply == "Answer."
    assert blocks == []
    assert "quiz" in caplog.text and "unparseable" in caplog.text


def test_text_without_blocks_is_unchanged():
    assert split_artifact_blocks("tutor", "Plain answer.\n") == ("Plain answer.\n", [])


def test_tool_artifacts_win_over_keys_and_blocks_of_the_same_type():
    calls = [ToolOutput("communications.draft_message", {"body_md": "from tool"},
                        {"draft_id": "d-1"})]
    output = {"send_ready_payload": {"body": "from key"}}
    blocks = [{"type": "message", "data": {"body": "from block"}}]

    collected = collect_artifacts("communication", output, calls, blocks)

    assert [a["data"]["body"] for a in collected] == ["from tool"]


TOOL_BUILT = [
    ("grading_assistant", "rubric_grades",
     ToolOutput("assessments.draft_grade", {"submission_id": "s-1", "scores": {"Thesis": 10}},
                {"grade_id": "g-1"})),
    ("communication", "message",
     ToolOutput("communications.draft_message", {"body_md": "Hello"}, {"draft_id": "d-1"})),
    ("assessment", "quiz",
     ToolOutput("assessments.create_question", {"stem": "Why?"}, {"question_id": "q-1"})),
    ("course_architect", "content_draft",
     ToolOutput("content.save_draft", {"title": "T", "body_md": "B"}, {"draft_id": "d-1"})),
    ("advising", "degree_audit",
     ToolOutput("sis.degree_audit", {"student_id": "p-1"}, {"program": "BS", "requirements": []})),
    ("accessibility", "wcag_report",
     ToolOutput("standards.check_wcag", {"content_id": "c-1"},
                {"findings": [{"criterion": "1.1.1", "status": "fail", "details": "No alt"}]})),
]


@pytest.mark.parametrize("agent, kind, call", TOOL_BUILT)
def test_instruction_lets_the_agent_skip_a_block_the_tool_already_builds(agent, kind, call):
    output = apply_post_processors(agent, {"response_markdown": "Done."}, [call])

    collected = collect_artifacts(agent, output, [call], blocks=[])

    assert [a["type"] for a in collected] == [kind]
    assert f"`{call.tool}` calls when one succeeded; then skip" in artifact_instruction(agent)


def test_instruction_requires_the_block_where_no_tool_builds_the_artifact():
    text = artifact_instruction("early_alert")

    assert "`risk_list`" in text
    assert "built by the system" not in text


def test_a_valid_block_of_a_type_the_agent_may_not_emit_is_dropped(caplog):
    quiz = {"title": "Q", "questions": [{"question": "Why?"}]}

    reply, blocks = split_artifact_blocks(
        "tutor", f"Answer.\n\n```artifact quiz\n{json.dumps(quiz)}\n```")

    assert reply == "Answer."
    assert blocks == []
    assert "Dropped artifact block of type 'quiz'" in caplog.text


def test_a_block_written_on_one_line_is_taken():
    quiz = {"title": "Q", "questions": [{"question": "Why?"}]}

    reply, blocks = split_artifact_blocks(
        "assessment", f"Answer.\n\n```artifact quiz {json.dumps(quiz)}```\n")

    assert reply == "Answer."
    assert blocks == [{"type": "quiz", "data": quiz}]


def test_output_keys_win_over_blocks_of_the_same_type():
    output = {"send_ready_payload": {"body": "from key"}}
    blocks = [{"type": "message", "data": {"body": "from block"}}]

    collected = collect_artifacts("communication", output, [], blocks)

    assert [a["data"]["body"] for a in collected] == ["from key"]


def test_instruction_lists_only_the_agents_types():
    text = artifact_instruction("early_alert")
    assert "`risk_list`" in text and "`quiz`" not in text
    assert artifact_instruction("learning_analyst") == ""


# --- through the runner and synthesize ---------------------------------------------------------


def _usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=10, output_tokens=5)


def _tool_use(tool_id: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="tool_use", usage=_usage(), content=[
        SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args)])


class _Client:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.messages = self
        self.systems: list[str] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.systems.append(kwargs["system"])
        return self._responses.pop(0)


class _ToolServer:
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results

    async def __call__(self, tool: str, args: dict[str, Any]) -> str:
        return json.dumps(self.results[tool])


async def test_runner_result_carries_rubric_grades_into_the_final_event(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    world = build_auth_world()
    server = _ToolServer({
        "assessments.get_rubric": RUBRIC,
        "assessments.get_submission": {
            "id": "sub-1", "person_id": world.people["student"].id,
            "body_md": "A long enough essay body " * 5, "submitted_at": "2026-09-30T10:00:00Z"},
        "assessments.draft_grade": {"grade_id": "grade-1"},
    })
    gateway = ToolGateway(server, directory=world.directory, objects=InMemoryObjectDirectory(
        {"sub-1": CS101.course_id, "rub-1": CS101.course_id}))
    client = _Client([
        _tool_use("tu1", "assessments_get_rubric", {"rubric_id": "rub-1"}),
        _tool_use("tu2", "assessments_get_submission", {"submission_id": "sub-1"}),
        _tool_use("tu3", "assessments_draft_grade", {
            "submission_id": "sub-1", "rubric_id": "rub-1",
            "scores": {"Thesis": 10, "Evidence": 3}, "feedback": {}, "graded_by": "x"}),
        SimpleNamespace(stop_reason="end_turn", usage=_usage(), content=[
            SimpleNamespace(type="text", text="Drafted one grade (not committed).")]),
    ])
    ctx = GatewayContext(auth=auth_context(world, "faculty"), session_id="sess-1",
                         turn_id="turn-1", step_id="s1")

    result = await ClaudeAgentRunner(client=client, gateway=gateway).run(
        "grading_assistant", {"message": "grade it", "_tool_context": ctx})

    assert result["success"] is True, result
    assert "ARTIFACTS:" in client.systems[0]
    assert [a["type"] for a in result["artifacts"]] == ["rubric_grades"]

    state = await synthesize({
        "agent_results": [{"step_id": "s1", "agent": "grading_assistant",
                           "output": result["output"], "artifacts": result["artifacts"],
                           "cost_usd": 0.0, "tokens": 0, "success": True}],
        "events_emitted": [],
    })
    final = state["events_emitted"][-1]
    assert final["event"] == "final"
    [artifact] = final["payload"]["artifacts"]
    assert artifact["artifact_id"] == "s1-rubric_grades-1"
    assert artifact["type"] == "rubric_grades"
    assert artifact["data"]["grade_id"] == "grade-1"


async def test_runner_strips_artifact_block_from_the_reply(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    world = build_auth_world()
    client = _Client([SimpleNamespace(stop_reason="end_turn", usage=_usage(), content=[
        SimpleNamespace(type="text", text=(
            "Ana is at risk.\n```artifact risk_list\n"
            '{"students": [{"name": "Ana", "risk_score": 0.7, "factors": []}]}\n```'))])])
    ctx = GatewayContext(auth=auth_context(world, "faculty"), session_id="sess-1",
                         turn_id="turn-1", step_id="s1")

    result = await ClaudeAgentRunner(client=client, gateway=ToolGateway(_ToolServer({}))).run(
        "early_alert", {"message": "who is at risk", "_tool_context": ctx})

    assert result["output"]["response_markdown"].startswith("Ana is at risk.")
    assert "```artifact" not in result["output"]["response_markdown"]
    assert [a["type"] for a in result["artifacts"]] == ["risk_list"]


async def test_runner_recounts_the_summary_of_a_wcag_report_block(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    world = build_auth_world()
    report = {
        "issues": [
            {"rule": "1.1.1", "severity": "error", "description": "img without alt"},
            {"rule": "1.4.3", "severity": "error", "description": "low contrast"},
            {"rule": "2.4.6", "severity": "warning", "description": "vague heading"},
        ],
        "summary": {"errors": 7, "warnings": 0, "passes": 12},
    }
    client = _Client([SimpleNamespace(stop_reason="end_turn", usage=_usage(), content=[
        SimpleNamespace(type="text", text=(
            "Two errors found.\n```artifact wcag_report\n" + json.dumps(report) + "\n```"))])])
    ctx = GatewayContext(auth=auth_context(world, "faculty"), session_id="sess-1",
                         turn_id="turn-1", step_id="s1")

    result = await ClaudeAgentRunner(client=client, gateway=ToolGateway(_ToolServer({}))).run(
        "accessibility", {"message": "check my page", "_tool_context": ctx})

    [artifact] = result["artifacts"]
    assert artifact["type"] == "wcag_report"
    assert artifact["data"]["summary"] == {"errors": 2, "warnings": 1, "passes": 12}


class _ChartRunner:
    async def run(self, agent: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"output": {"response_markdown": "ok"}, "success": True, "tool_calls": [],
                "artifacts": [{"type": "chart", "data": {"x_key": "x"}}]}


async def test_dispatch_keeps_artifacts_out_of_the_agent_result_event():
    set_agent_runner(_ChartRunner())
    try:
        state = await dispatch({
            "plan": {"strategy": "react", "steps": [
                {"step_id": "s1", "agent": "engagement_analyst", "depends_on": []}]},
            "current_message": "trends", "persona": "faculty", "events_emitted": [],
            "agent_results": [],
        })
    finally:
        set_agent_runner(None)

    [result] = state["agent_results"]
    assert result["artifacts"] == [{"type": "chart", "data": {"x_key": "x"}}]
    event = next(e for e in state["events_emitted"] if e["event"] == "agent_result")
    assert "artifacts" not in event["payload"]


# --- block validation (ARTIFACTS.md) -----------------------------------------------------------


@pytest.mark.parametrize(("agent", "kind", "data"), [
    ("assessment", "quiz", {"title": "Quiz", "questions": []}),
    ("assessment", "quiz", {"questions": [{"stem": "no question key"}]}),
    ("early_alert", "risk_list", {"title": "At risk"}),
    ("early_alert", "risk_list", {"students": [{"risk_score": 0.9}]}),
    ("accessibility", "wcag_report", {"summary": {"errors": 1}}),
    ("communication", "message", {"subject": "Hi", "body": "  "}),
    ("advising", "learning_path", {"nodes": [{"id": "n1"}]}),
    ("engagement_analyst", "chart", {"data": [{"x": 1}], "x_key": "x", "y_keys": []}),
    ("grading_assistant", "rubric_grades", {"criteria": []}),
    ("advising", "degree_audit", {"requirements": []}),
])
def test_block_missing_required_fields_is_dropped(
    agent: str, kind: str, data: dict[str, Any], caplog: pytest.LogCaptureFixture,
):
    text = f"Answer.\n```artifact {kind}\n{json.dumps(data)}\n```"

    reply, blocks = split_artifact_blocks(agent, text)

    assert reply == "Answer."
    assert blocks == []
    assert "missing required fields" in caplog.text


def test_minimal_valid_block_of_every_type_is_kept():
    minimal = {
        "quiz": {"questions": [{"question": "What is ATP?"}]},
        "risk_list": {"students": []},
        "wcag_report": {"issues": [{"rule": "1.1.1"}]},
        "content_draft": {"body_md": "# Syllabus"},
        "message": {"body": "Hello"},
        "learning_path": {"nodes": [{"id": "n1", "label": "Recursion"}]},
        "rubric_grades": {"criteria": [{"name": "Thesis"}]},
        "chart": {"data": [], "x_key": "week", "y_keys": ["logins"]},
        "degree_audit": {"program": "BS CS", "requirements": []},
    }
    owner = {t: a for a, types in AGENT_ARTIFACT_TYPES.items() for t in types}

    for kind, data in minimal.items():
        _, blocks = split_artifact_blocks(owner[kind], f"x\n```artifact:{kind}\n{json.dumps(data)}\n```")
        assert [b["type"] for b in blocks] == [kind], kind


def test_content_draft_block_without_body_uses_the_reply():
    text = ("# Intro to Data Ethics\n\nWeek 1: Foundations.\n\n"
            '```artifact content_draft\n{"title": "Intro to Data Ethics", "kind": "syllabus"}\n```')

    reply, [block] = split_artifact_blocks("course_architect", text)

    assert reply == "# Intro to Data Ethics\n\nWeek 1: Foundations."
    assert block == {"type": "content_draft", "data": {
        "title": "Intro to Data Ethics", "kind": "syllabus", "body_md": reply}}


def test_block_cut_off_by_the_token_cap_is_removed_from_the_reply(
    caplog: pytest.LogCaptureFixture,
):
    text = 'Ten questions follow.\n\n```artifact quiz\n{"title": "Photosynthesis", "questions": [{"que'

    reply, blocks = split_artifact_blocks("assessment", text)

    assert reply == "Ten questions follow."
    assert blocks == []
    assert "unterminated" in caplog.text


def test_instruction_explains_the_content_draft_body_shortcut_only_where_it_applies():
    assert "leave out `body_md`" in artifact_instruction("course_architect")
    assert "leave out `body_md`" not in artifact_instruction("assessment")


def test_code_fence_inside_a_json_string_does_not_close_the_block():
    quiz = {"title": "Loops", "questions": [
        {"question": "What does this print?\n```python\nprint(1)\n```", "type": "short_answer"}]}
    text = "Here is your quiz.\n\n```artifact quiz\n" + json.dumps(quiz) + "\n```"

    reply, blocks = split_artifact_blocks("assessment", text)

    assert reply == "Here is your quiz."
    assert blocks == [{"type": "quiz", "data": quiz}]


def test_block_with_crlf_line_endings_is_parsed_and_removed():
    text = ("Two students need attention.\r\n\r\n```artifact risk_list\r\n"
            '{"students": [{"name": "Ana", "risk_score": 0.8, "factors": []}]}\r\n```\r\n')

    reply, [block] = split_artifact_blocks("early_alert", text)

    assert reply == "Two students need attention."
    assert block["type"] == "risk_list"


def test_closing_fence_on_the_same_line_as_the_object_is_accepted():
    text = 'Answer.\n```artifact risk_list\n{"students": [{"name": "Ana", "risk_score": 0.8}]}```'

    reply, [block] = split_artifact_blocks("early_alert", text)

    assert reply == "Answer."
    assert block["data"]["students"][0]["name"] == "Ana"


def test_cut_off_block_with_a_code_fence_in_a_string_is_removed(
    caplog: pytest.LogCaptureFixture,
):
    text = 'Quiz.\n\n```artifact quiz\n{"questions": [{"question": "x\\n```python\\nprint(1)\\n```'

    reply, blocks = split_artifact_blocks("assessment", text)

    assert reply == "Quiz."
    assert blocks == []
    assert "unterminated" in caplog.text
