"""Scenario executor: runs a scenario YAML against a live API."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from .models import Scenario


@dataclass
class ScenarioResult:
    scenario_id: int
    scenario_name: str
    passed: bool
    wall_time_ms: float
    agent_invocations: int
    artifacts: list[str]
    events: list[dict[str, Any]]
    errors: list[str] = field(default_factory=list)


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

    def run(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario end-to-end."""
        events: list[dict[str, Any]] = []
        errors: list[str] = []
        agent_invocations = 0
        artifacts: list[str] = []

        start_time = time.monotonic()

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

                    for turn in scenario.user_turns:
                        approval_index = 0

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
                                    errors.append(f"Unparseable SSE data line: {raw[:200]}")
                                    continue

                                events.append(event)
                                event_type = event.get("event", "")

                                if event_type == "agent_start":
                                    agent_invocations += 1

                                if event_type == "agent_result":
                                    for artifact in event.get("payload", {}).get("artifacts", []):
                                        artifacts.append(artifact.get("type", "unknown"))

                                if event_type == "approval_request":
                                    if approval_index < len(turn.approvals):
                                        approval = turn.approvals[approval_index]
                                        client.post(
                                            "/api/approval",
                                            json={
                                                "session_id": session_id,
                                                "turn_id": turn_id,
                                                "approval_id": event.get("payload", {}).get(
                                                    "approval_id"
                                                ),
                                                "decision": approval.decision,
                                                "edited_payload": approval.edits,
                                            },
                                            headers=self._csrf_headers(client),
                                        ).raise_for_status()
                                        approval_index += 1
                                    else:
                                        errors.append(
                                            f"Unexpected approval_request (no scripted approval at index {approval_index})"
                                        )

                                if event_type in ("final", "error"):
                                    break
                finally:
                    self._logout(client, errors)

        except Exception as e:
            errors.append(f"Executor error: {type(e).__name__}: {e}")

        wall_time_ms = (time.monotonic() - start_time) * 1000

        # 3. Validate against expected
        passed = True

        # Check final event
        if events:
            last_event_type = events[-1].get("event", "")
            if last_event_type != scenario.expected.final_event:
                errors.append(
                    f"Expected final event '{scenario.expected.final_event}', got '{last_event_type}'"
                )
                passed = False
        else:
            errors.append("No events received")
            passed = False

        # Check artifacts
        for expected_type in scenario.expected.artifacts_of_type:
            if expected_type not in artifacts:
                errors.append(f"Missing expected artifact type: {expected_type}")
                passed = False

        # Check agent invocations
        if agent_invocations < scenario.expected.min_agent_invocations:
            errors.append(
                f"Expected >= {scenario.expected.min_agent_invocations} agent invocations, got {agent_invocations}"
            )
            passed = False

        # Check wall time
        if wall_time_ms > scenario.expected.max_wall_time_ms:
            errors.append(
                f"Wall time {wall_time_ms:.0f}ms exceeded max {scenario.expected.max_wall_time_ms}ms"
            )
            passed = False

        if errors:
            passed = False

        return ScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=passed,
            wall_time_ms=wall_time_ms,
            agent_invocations=agent_invocations,
            artifacts=artifacts,
            events=events,
            errors=errors,
        )
