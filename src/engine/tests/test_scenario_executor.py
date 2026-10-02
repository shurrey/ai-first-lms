"""Scenario executor behaviour the engine's final event drives: artifacts, approvals, xfail."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.platform.scenarios.executor import ScenarioExecutor, load_all_scenarios  # noqa: E402
from src.platform.scenarios.models import Scenario  # noqa: E402

CONTRACT_TYPES = {
    "rubric_grades", "message", "quiz", "chart", "degree_audit",
    "content_draft", "wcag_report", "risk_list", "learning_path",
}


class _Api:
    def __init__(self, events: list[dict[str, Any]], brief: bool = False) -> None:
        self.events = events
        self.brief = brief
        self.approvals: list[dict[str, Any]] = []
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        turn = request.url.params.get("turn_id")
        self.calls.append(f"{path}?{turn}" if turn else path)
        if path == "/api/auth/login":
            return httpx.Response(200, json={"active_role": "faculty"}, headers=[
                ("set-cookie", "lms_session=tok; Path=/"), ("set-cookie", "lms_csrf=c; Path=/")])
        if path == "/api/session":
            return httpx.Response(200, json={"session_id": "s1", **(
                {"brief_turn_id": "brief-s1"} if self.brief else {})})
        if path == "/api/converse":
            return httpx.Response(202, json={"turn_id": "t1"})
        if path == "/api/stream" and turn == "brief-s1":
            body = f"data: {json.dumps({'event': 'final', 'payload': {'artifacts': []}})}\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if path == "/api/stream":
            body = "".join(f"data: {json.dumps(e)}\n\n" for e in self.events)
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if path == "/api/approval":
            self.approvals.append(json.loads(request.content))
            return httpx.Response(202, json={"status": "accepted"})
        if path == "/api/auth/logout":
            return httpx.Response(204)
        return httpx.Response(404)


def _run(events: list[dict[str, Any]], brief: bool = False,
         **overrides: Any) -> tuple[Any, _Api]:
    data: dict[str, Any] = {
        "id": 1, "name": "t", "login_as": "m.torres@university.edu", "course_id": "cs101",
        "user_turns": [{"message": "go"}],
        "expected": {"artifacts_of_type": ["rubric_grades"], "min_agent_invocations": 1},
    }
    data.update(overrides)
    api = _Api(events, brief)
    executor = ScenarioExecutor(base_url="http://test", password="pw-for-tests-only",
                                transport=httpx.MockTransport(api.handler))
    return executor.run(Scenario(**data)), api


def _final(*types: str) -> dict[str, Any]:
    return {"event": "final", "payload": {"artifacts": [
        {"artifact_id": f"a{i}", "type": t, "data": {}} for i, t in enumerate(types)]}}


def test_artifacts_are_read_from_the_final_event():
    result, _ = _run([{"event": "agent_start", "payload": {}}, _final("rubric_grades")])

    assert result.errors == []
    assert result.status == "pass" and result.passed
    assert result.artifacts == ["rubric_grades"]


def test_session_brief_is_drained_before_the_first_turn():
    result, api = _run([{"event": "agent_start", "payload": {}}, _final("rubric_grades")],
                       brief=True)

    assert result.status == "pass"
    assert api.calls.index("/api/stream?brief-s1") < api.calls.index("/api/converse")
    assert result.artifacts == ["rubric_grades"]


def test_xfail_scenario_that_fails_reports_xfail_without_failing_the_run():
    result, _ = _run([{"event": "agent_start", "payload": {}}, _final()], xfail="needs T-D-104")

    assert result.status == "xfail"
    assert result.passed
    assert result.xfail_reason == "needs T-D-104"
    assert any("rubric_grades" in e for e in result.errors)


def test_xfail_scenario_that_passes_reports_xpass():
    result, _ = _run([{"event": "agent_start", "payload": {}}, _final("rubric_grades")],
                     xfail="needs T-D-104")

    assert result.status == "xpass"


def test_default_approval_answers_unscripted_requests():
    events = [{"event": "agent_start", "payload": {}}] + [
        {"event": "approval_request", "payload": {"approval_id": f"ap{i}"}} for i in range(3)
    ] + [_final("rubric_grades")]

    result, api = _run(events, user_turns=[{
        "message": "go", "approvals": [{"decision": "edit", "edits": {"x": 1}}],
        "default_approval": {"decision": "approve"}}])

    assert result.errors == []
    assert [a["decision"] for a in api.approvals] == ["edit", "approve", "approve"]


def test_unscripted_approval_is_rejected_and_fails_the_scenario():
    events = [{"event": "agent_start", "payload": {}},
              {"event": "approval_request", "payload": {"approval_id": "ap1"}},
              _final("rubric_grades")]

    result, api = _run(events)

    assert result.status == "fail"
    assert [a["decision"] for a in api.approvals] == ["reject"]


def test_repo_scenarios_expect_contract_artifact_types_and_realistic_caps():
    scenarios = load_all_scenarios(ROOT / "src" / "platform" / "scenarios")

    for s in scenarios:
        assert set(s.expected.artifacts_of_type) <= CONTRACT_TYPES, s.id
        cap = 120_000 if s.expected.min_agent_invocations > 1 else 60_000
        assert s.expected.max_wall_time_ms == cap, s.id
    assert [s.id for s in scenarios if s.xfail] == [3]
