"""Scenario executor: runs a scenario YAML against a live API."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml

from .models import ApprovalAction, Scenario, UserTurn

ScenarioStatus = Literal["pass", "fail", "xfail", "xpass"]


@dataclass
class ScenarioResult:
    """`passed` is False only for status "fail"; a failing xfail scenario does not fail a run.

    `wall_time_ms` runs from each message's send to its last event, summed over turns, minus
    the time spent answering approval requests; the session brief is not included.
    """

    scenario_id: int
    scenario_name: str
    passed: bool
    wall_time_ms: float
    agent_invocations: int
    artifacts: list[str]
    events: list[dict[str, Any]]
    errors: list[str] = field(default_factory=list)
    status: ScenarioStatus = "pass"
    xfail_reason: str | None = None


def load_scenario(path: str | Path) -> Scenario:
    """Load and validate a scenario YAML file."""
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)
    return Scenario(**data)


def load_all_scenarios(directory: str | Path) -> list[Scenario]:
    """Load all scenario YAML files from a directory, sorted by id."""
    directory = Path(directory)
    scenarios = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        if yaml_file.name == "README.md":
            continue
        scenarios.append(load_scenario(yaml_file))
    return sorted(scenarios, key=lambda s: s.id)


PASSWORD_ENV = "SEED_DEMO_PASSWORD"
SESSION_COOKIE = "lms_session"
CSRF_COOKIE = "lms_csrf"
CSRF_HEADER = "X-CSRF-Token"
BRIEF_TIMEOUT_S = 120


class ScenarioExecutor:
    """Executes scenarios against the orchestrator API as a signed-in seeded person.

    The password defaults to $SEED_DEMO_PASSWORD, read at run time. `transport` is for tests.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        password: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._password = password
        self._transport = transport

    def _resolve_password(self) -> str:
        password = self._password if self._password is not None else os.environ.get(PASSWORD_ENV)
        if not password:
            raise RuntimeError(
                f"{PASSWORD_ENV} is not set; scenarios log in with the seeded demo password"
            )
        return password

    @staticmethod
    def _csrf_headers(client: httpx.Client) -> dict[str, str]:
        token = client.cookies.get(CSRF_COOKIE)
        if not token:
            raise RuntimeError(f"No {CSRF_COOKIE} cookie; log in before calling non-GET endpoints")
        return {CSRF_HEADER: token}

    def _login(self, client: httpx.Client, scenario: Scenario) -> None:
        resp = client.post(
            "/api/auth/login",
            json={"username": scenario.login_as, "password": self._resolve_password()},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Login as {scenario.login_as} failed: HTTP {resp.status_code}")
        if not client.cookies.get(SESSION_COOKIE):
            raise RuntimeError(
                f"Login as {scenario.login_as} did not set the {SESSION_COOKIE} cookie"
            )

        me = resp.json()
        if scenario.active_role and me.get("active_role") != scenario.active_role:
            client.post(
                "/api/auth/role",
                json={"role": scenario.active_role},
                headers=self._csrf_headers(client),
            ).raise_for_status()

    def _logout(self, client: httpx.Client, errors: list[str]) -> None:
        """Records a failure in `errors` rather than raising over the scenario's own error."""
        try:
            client.post(
                "/api/auth/logout", headers=self._csrf_headers(client)
            ).raise_for_status()
        except Exception as e:
            errors.append(f"Logout failed: {type(e).__name__}: {e}")

    def _drain_brief(self, client: httpx.Client, session_id: str, brief_turn_id: str | None,
                     errors: list[str]) -> None:
        """Waits for the session's opening brief, as the UI does, so the first turn's history
        is the same on every run (recorded LLM fixtures depend on it)."""
        if not brief_turn_id:
            return
        try:
            with client.stream(
                "GET", "/api/stream",
                params={"session_id": session_id, "turn_id": brief_turn_id},
                timeout=httpx.Timeout(connect=10, read=BRIEF_TIMEOUT_S, write=10, pool=10),
            ) as stream:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if event.get("event") == "error":
                        errors.append(f"Session brief failed: {event.get('payload')}")
                    if event.get("event") in ("final", "error"):
                        return
        except httpx.HTTPError as e:
            errors.append(f"Session brief stream failed: {type(e).__name__}: {e}")

    def run(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario end-to-end."""
        log = _TurnLog()

        try:
            with httpx.Client(
                base_url=self.base_url, timeout=10, transport=self._transport
            ) as client:
                self._login(client, scenario)
                try:
                    resp = client.post(
                        "/api/session",
                        json={"course_id": scenario.course_id},
                        headers=self._csrf_headers(client),
                    )
                    resp.raise_for_status()
                    session_data = resp.json()
                    session_id = session_data.get("session_id", session_data.get("id"))
                    self._drain_brief(client, session_id, session_data.get("brief_turn_id"),
                                      log.errors)
                    for turn in scenario.user_turns:
                        self._run_turn(client, scenario, session_id, turn, log)
                        if log.clarified:
                            break
                finally:
                    self._logout(client, log.errors)

        except Exception as e:
            log.errors.append(f"Executor error: {type(e).__name__}: {e}")

        return _validate(scenario, log)

    def _run_turn(self, client: httpx.Client, scenario: Scenario, session_id: str,
                  turn: UserTurn, log: _TurnLog) -> None:
        """Sends one message and follows its stream to `final`, `error` or `clarify`.

        Adds the turn's time from send to its last event, minus the time spent answering
        approval requests, to `log.active_ms`, even when a request raises.
        """
        approval_index = 0
        sent_at = time.monotonic()
        approval_wait_s = 0.0
        try:
            resp = client.post(
                "/api/converse",
                json={"session_id": session_id, "message": turn.message},
                headers=self._csrf_headers(client),
            )
            resp.raise_for_status()
            turn_data = resp.json()
            turn_id = turn_data.get("turn_id", turn_data.get("id"))

            with client.stream(
                "GET",
                "/api/stream",
                params={"session_id": session_id, "turn_id": turn_id},
                timeout=httpx.Timeout(
                    connect=10,
                    read=scenario.expected.max_wall_time_ms / 1000 + 5,
                    write=10,
                    pool=10,
                ),
            ) as stream:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        log.errors.append(f"Unparseable SSE data line: {raw[:200]}")
                        continue

                    log.events.append(event)
                    event_type = event.get("event", "")
                    payload = event.get("payload") or {}

                    if event_type == "agent_start":
                        log.agent_invocations += 1

                    if event_type in ("agent_result", "final"):
                        for artifact in payload.get("artifacts") or []:
                            log.artifacts.append(artifact.get("type", "unknown"))

                    if event_type == "approval_request":
                        requested_at = time.monotonic()
                        self._answer_approval(client, session_id, turn_id, turn,
                                              approval_index, payload, log.errors)
                        approval_wait_s += time.monotonic() - requested_at
                        approval_index += 1

                    if event_type == "clarify":
                        # Scenarios are scripted to be answerable without a follow-up.
                        log.clarified = True
                        log.errors.append(
                            "The turn asked a clarifying question instead of answering: "
                            f"{payload.get('question')!r}"
                        )
                        break

                    if event_type in ("final", "error"):
                        break
        finally:
            log.active_ms += (time.monotonic() - sent_at - approval_wait_s) * 1000

    def _answer_approval(self, client: httpx.Client, session_id: str, turn_id: str,
                         turn: UserTurn, index: int, payload: dict[str, Any],
                         errors: list[str]) -> None:
        approval = _approval_for(turn, index)
        if approval is None:
            errors.append(
                f"Unexpected approval_request (no scripted approval at index {index}); "
                "rejected it"
            )
            approval = ApprovalAction(decision="reject")
        client.post(
            "/api/approval",
            json={
                "session_id": session_id,
                "turn_id": turn_id,
                "approval_id": payload.get("approval_id"),
                "decision": approval.decision,
                "edited_payload": approval.edits,
            },
            headers=self._csrf_headers(client),
        ).raise_for_status()


@dataclass
class _TurnLog:
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    agent_invocations: int = 0
    # Send-to-last-event time summed over turns, excluding approval round trips.
    active_ms: float = 0.0
    clarified: bool = False


def _validate(scenario: Scenario, log: _TurnLog) -> ScenarioResult:
    errors = log.errors
    expected = scenario.expected

    if log.events:
        last_event_type = log.events[-1].get("event", "")
        if last_event_type != expected.final_event:
            errors.append(
                f"Expected final event '{expected.final_event}', got '{last_event_type}'"
            )
    else:
        errors.append("No events received")

    for expected_type in expected.artifacts_of_type:
        if expected_type not in log.artifacts:
            errors.append(f"Missing expected artifact type: {expected_type}")

    if log.agent_invocations < expected.min_agent_invocations:
        errors.append(
            f"Expected >= {expected.min_agent_invocations} agent invocations, "
            f"got {log.agent_invocations}"
        )

    if log.active_ms > expected.max_wall_time_ms:
        errors.append(
            f"Wall time {log.active_ms:.0f}ms (approval waits excluded) exceeded max "
            f"{expected.max_wall_time_ms}ms"
        )

    passed = not errors
    status: ScenarioStatus
    if scenario.xfail is None:
        status = "pass" if passed else "fail"
    else:
        status = "xpass" if passed else "xfail"

    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        passed=status != "fail",
        status=status,
        xfail_reason=scenario.xfail,
        wall_time_ms=log.active_ms,
        agent_invocations=log.agent_invocations,
        artifacts=log.artifacts,
        events=log.events,
        errors=errors,
    )


def _approval_for(turn: UserTurn, index: int) -> ApprovalAction | None:
    """The scripted decision for the turn's `index`-th approval request, if any."""
    if index < len(turn.approvals):
        return turn.approvals[index]
    return turn.default_approval
