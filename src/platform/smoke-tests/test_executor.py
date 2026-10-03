#!/usr/bin/env python3
"""Tests for the scenario executor: loading, validation, and runs against a fake API."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.platform.scenarios.executor import (  # noqa: E402
    ScenarioExecutor,
    load_all_scenarios,
    load_scenario,
)
from src.platform.scenarios.models import (  # noqa: E402
    ApprovalAction,
    ExpectedOutcome,
    Scenario,
    UserTurn,
)

SCENARIOS_DIR = ROOT / "src" / "platform" / "scenarios"
SEEDED_STUDENT = "emma.smith@student.edu"
SEEDED_FACULTY = "m.torres@university.edu"
BIO150_FACULTY = "m.patel@university.edu"
TEST_PASSWORD = "not-the-demo-password-1234"
CSRF = "csrf-abc"


def _write_yaml(data: dict) -> Path:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
    return Path(f.name)


def _scenario(**overrides) -> Scenario:
    data = {
        "id": 1,
        "name": "Test",
        "login_as": SEEDED_STUDENT,
        "course_id": "cs101",
        "user_turns": [{"message": "Hi"}],
        "expected": {"final_event": "final", "min_agent_invocations": 1},
    }
    data.update(overrides)
    return Scenario(**data)


def test_load_scenario():
    path = _write_yaml(
        {
            "id": 1,
            "name": "Test scenario",
            "login_as": SEEDED_STUDENT,
            "active_role": "student",
            "course_id": "cs101",
            "user_turns": [{"message": "Hello, can you help me?"}],
            "expected": {
                "final_event": "final",
                "min_agent_invocations": 1,
                "max_wall_time_ms": 10000,
            },
        }
    )
    scenario = load_scenario(path)

    assert scenario.id == 1
    assert scenario.login_as == SEEDED_STUDENT
    assert scenario.active_role == "student"
    assert scenario.user_turns[0].message == "Hello, can you help me?"
    assert scenario.expected.final_event == "final"


def test_load_scenario_with_approvals():
    path = _write_yaml(
        {
            "id": 10,
            "name": "Multi-agent with approvals",
            "login_as": SEEDED_FACULTY,
            "course_id": "cs101",
            "user_turns": [
                {
                    "message": "Create a study guide and send it.",
                    "approvals": [
                        {"decision": "approve"},
                        {"decision": "edit", "edits": {"tone": "formal"}},
                    ],
                }
            ],
            "expected": {
                "artifacts_of_type": ["content_draft", "message"],
                "min_agent_invocations": 3,
            },
        }
    )
    scenario = load_scenario(path)

    assert [a.decision for a in scenario.user_turns[0].approvals] == ["approve", "edit"]
    assert scenario.user_turns[0].approvals[1].edits == {"tone": "formal"}
    assert scenario.active_role is None


def test_load_all_scenarios_sorted_by_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in [3, 1, 2]:
            data = {
                "id": i,
                "name": f"Scenario {i}",
                "login_as": SEEDED_STUDENT,
                "course_id": "cs101",
                "user_turns": [{"message": f"Message {i}"}],
                "expected": {"final_event": "final"},
            }
            (Path(tmpdir) / f"{i:02d}-test.yaml").write_text(yaml.dump(data))

        assert [s.id for s in load_all_scenarios(tmpdir)] == [1, 2, 3]


def test_model_defaults():
    s = Scenario(
        id=1,
        name="Test",
        login_as=SEEDED_STUDENT,
        course_id="cs101",
        user_turns=[UserTurn(message="Hi")],
        expected=ExpectedOutcome(),
    )
    assert s.expected.final_event == "final"
    assert s.expected.max_wall_time_ms == 30000
    assert ApprovalAction(decision="approve").edits is None


def test_login_as_is_required():
    with pytest.raises(ValidationError):
        Scenario(id=1, name="x", course_id="cs101", user_turns=[], expected=ExpectedOutcome())


def test_persona_field_is_rejected():
    with pytest.raises(ValidationError):
        _scenario(persona="student")


def test_unknown_active_role_is_rejected():
    with pytest.raises(ValidationError):
        _scenario(active_role="superuser")


def test_repo_scenarios_log_in_as_seeded_people():
    scenarios = load_all_scenarios(SCENARIOS_DIR)
    assert [s.id for s in scenarios] == list(range(1, 12))
    for s in scenarios:
        assert s.login_as in {SEEDED_STUDENT, SEEDED_FACULTY, BIO150_FACULTY}, s.id
        expected_role = "student" if s.login_as == SEEDED_STUDENT else "faculty"
        assert s.active_role == expected_role, s.id


@pytest.mark.parametrize("scenario_id", [2, 6])
def test_biology_scenarios_run_in_bio150_as_its_instructor(scenario_id):
    s = next(s for s in load_all_scenarios(SCENARIOS_DIR) if s.id == scenario_id)
    assert (s.login_as, s.course_id) == (BIO150_FACULTY, "bio150")


def test_accessibility_scenario_names_the_seeded_biology_course():
    s = next(s for s in load_all_scenarios(SCENARIOS_DIR) if s.id == 6)
    assert "General Biology" in s.user_turns[0].message
    assert "Intro to Biology" not in s.user_turns[0].message


def test_repo_scenario_caps_are_60s_single_agent_and_120s_multi_agent():
    # A scenario whose SPEC-v1 §9 plan may use a second agent (e.g. 8) can take the 120 s cap
    # while still requiring only one invocation.
    for s in load_all_scenarios(SCENARIOS_DIR):
        assert s.expected.max_wall_time_ms in (60_000, 120_000), s.id
        if s.expected.min_agent_invocations > 1:
            assert s.expected.max_wall_time_ms == 120_000, s.id


def test_grading_scenario_xfails_on_t_e_134_with_the_turn_budget_for_dr_torres_in_cs101():
    s = next(s for s in load_all_scenarios(SCENARIOS_DIR) if s.id == 3)
    assert s.xfail is not None and "T-E-134" in s.xfail and "T-C-116" not in s.xfail
    assert s.expected.max_wall_time_ms == 120_000
    assert (s.login_as, s.course_id) == (SEEDED_FACULTY, "cs101")


class FakeApi:
    """Minimal orchestrator: cookie login, CSRF double-submit, one-turn SSE stream."""

    def __init__(
        self,
        *,
        login_status: int = 200,
        login_role: str = "student",
        events: list[dict] | None = None,
        session_status: int = 200,
        approval_delay_s: float = 0.0,
        logout_delay_s: float = 0.0,
    ):
        self.approval_delay_s = approval_delay_s
        self.logout_delay_s = logout_delay_s
        self.login_status = login_status
        self.login_role = login_role
        self.session_status = session_status
        self.events = (
            events
            if events is not None
            else [
                {"event": "agent_start", "payload": {}},
                {"event": "agent_result", "payload": {"artifacts": [{"type": "explanation"}]}},
                {"event": "final", "payload": {}},
            ]
        )
        self.requests: list[httpx.Request] = []

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]

    def body(self, path: str) -> dict:
        req = next(r for r in self.requests if r.url.path == path)
        return json.loads(req.content)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/api/auth/login":
            if self.login_status != 200:
                return httpx.Response(
                    self.login_status, json={"detail": "Invalid username or password."}
                )
            return httpx.Response(
                200,
                json={"active_role": self.login_role, "roles": [self.login_role]},
                headers=[
                    ("set-cookie", "lms_session=tok123; HttpOnly; SameSite=Lax; Path=/"),
                    ("set-cookie", f"lms_csrf={CSRF}; SameSite=Lax; Path=/"),
                ],
            )

        if "lms_session=tok123" not in request.headers.get("cookie", ""):
            return httpx.Response(401, json={"detail": "Not signed in"})
        if request.method != "GET" and request.headers.get("x-csrf-token") != CSRF:
            return httpx.Response(403, json={"detail": "CSRF"})

        if path == "/api/auth/role":
            return httpx.Response(200, json={"active_role": json.loads(request.content)["role"]})
        if path == "/api/session":
            if self.session_status != 200:
                return httpx.Response(self.session_status, json={"detail": "refused"})
            return httpx.Response(200, json={"session_id": "s1"})
        if path == "/api/converse":
            return httpx.Response(202, json={"turn_id": "t1"})
        if path == "/api/stream":
            body = "".join(f"data: {json.dumps(e)}\n\n" for e in self.events)
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if path == "/api/approval":
            time.sleep(self.approval_delay_s)
            body = json.loads(request.content)
            if not body.get("approval_id"):
                return httpx.Response(422, json={"detail": "approval_id required"})
            return httpx.Response(
                202,
                json={
                    "status": "accepted",
                    "approval_id": body["approval_id"],
                    "decision": body["decision"],
                },
            )
        if path == "/api/auth/logout":
            time.sleep(self.logout_delay_s)
            return httpx.Response(204)
        return httpx.Response(404)


def _executor(api: FakeApi, password: str | None = TEST_PASSWORD) -> ScenarioExecutor:
    return ScenarioExecutor(
        base_url="http://test", password=password, transport=httpx.MockTransport(api.handler)
    )


def test_run_logs_in_and_carries_cookie_and_csrf():
    api = FakeApi()
    result = _executor(api).run(_scenario(active_role="student"))

    assert result.errors == []
    assert result.passed
    assert api.paths() == [
        "POST /api/auth/login",
        "POST /api/session",
        "POST /api/converse",
        "GET /api/stream",
        "POST /api/auth/logout",
    ]
    assert api.body("/api/auth/login") == {"username": SEEDED_STUDENT, "password": TEST_PASSWORD}
    assert "x-csrf-token" not in api.requests[0].headers
    stream_req = next(r for r in api.requests if r.url.path == "/api/stream")
    assert "x-csrf-token" not in stream_req.headers


def test_logout_still_runs_when_a_later_request_fails():
    api = FakeApi(session_status=403)
    result = _executor(api).run(_scenario())

    assert not result.passed
    assert api.paths() == ["POST /api/auth/login", "POST /api/session", "POST /api/auth/logout"]
    assert any("403" in e for e in result.errors)


def test_session_request_omits_persona_and_person_id():
    api = FakeApi()
    _executor(api).run(_scenario())

    assert api.body("/api/session") == {"course_id": "cs101"}


def test_run_switches_role_when_login_default_differs():
    api = FakeApi(login_role="program_lead")
    result = _executor(api).run(_scenario(login_as=SEEDED_FACULTY, active_role="faculty"))

    assert result.passed, result.errors
    assert api.paths()[:3] == ["POST /api/auth/login", "POST /api/auth/role", "POST /api/session"]
    assert api.body("/api/auth/role") == {"role": "faculty"}


def test_run_posts_scripted_approval_with_csrf():
    api = FakeApi(
        events=[
            {"event": "agent_start", "payload": {}},
            {"event": "approval_request", "payload": {"approval_id": "a1"}},
            {"event": "final", "payload": {}},
        ]
    )
    scenario = _scenario(
        login_as=SEEDED_FACULTY,
        user_turns=[
            {
                "message": "Grade it",
                "approvals": [{"decision": "edit", "edits": {"score": 9}}],
            }
        ],
    )
    result = _executor(api).run(scenario)

    assert result.passed, result.errors
    approval = api.body("/api/approval")
    assert approval == {
        "session_id": "s1",
        "turn_id": "t1",
        "approval_id": "a1",
        "decision": "edit",
        "edited_payload": {"score": 9},
    }


def test_failed_login_fails_scenario_without_leaking_password():
    api = FakeApi(login_status=401)
    result = _executor(api).run(_scenario())

    assert not result.passed
    assert api.paths() == ["POST /api/auth/login"]
    assert any("Login as emma.smith@student.edu failed: HTTP 401" in e for e in result.errors)
    assert all(TEST_PASSWORD not in e for e in result.errors)


def test_missing_password_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("SEED_DEMO_PASSWORD", raising=False)
    api = FakeApi()
    result = _executor(api, password=None).run(_scenario())

    assert not result.passed
    assert api.requests == []
    assert any("SEED_DEMO_PASSWORD is not set" in e for e in result.errors)


def test_password_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("SEED_DEMO_PASSWORD", "from-env-password-99")
    api = FakeApi()
    _executor(api, password=None).run(_scenario())

    assert api.body("/api/auth/login")["password"] == "from-env-password-99"


def test_clarify_fails_the_scenario_with_the_question_and_skips_later_turns():
    api = FakeApi(
        events=[
            {"event": "reasoning", "payload": {"step": "interpret"}},
            {"event": "clarify", "payload": {"question": "Which course?", "reason": "r"}},
            {"event": "reasoning", "payload": {"step": "clarify"}},
        ]
    )
    result = _executor(api).run(
        _scenario(user_turns=[{"message": "Draft it"}, {"message": "Second turn"}])
    )

    assert result.status == "fail"
    assert any("clarifying question" in e and "Which course?" in e for e in result.errors)
    assert api.paths().count("POST /api/converse") == 1


def test_time_answering_approvals_is_not_counted_against_the_cap():
    api = FakeApi(
        approval_delay_s=0.3,
        events=[
            {"event": "agent_start", "payload": {}},
            {"event": "approval_request", "payload": {"approval_id": "a1"}},
            {"event": "final", "payload": {}},
        ],
    )
    scenario = _scenario(
        user_turns=[{"message": "Send it", "approvals": [{"decision": "approve"}]}],
        expected={"final_event": "final", "min_agent_invocations": 1,
                  "max_wall_time_ms": 200},
    )
    result = _executor(api).run(scenario)

    assert result.errors == []
    assert result.wall_time_ms < 200


def test_logout_time_is_not_counted_against_the_cap():
    api = FakeApi(logout_delay_s=0.3)
    scenario = _scenario(
        expected={"final_event": "final", "min_agent_invocations": 1, "max_wall_time_ms": 200}
    )
    result = _executor(api).run(scenario)

    assert result.errors == []
