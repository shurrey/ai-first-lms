"""Scenario executor: runs a scenario YAML against a live API."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


class ScenarioExecutor:
    """Executes scenarios against the orchestrator API."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url.rstrip("/")

    def run(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario end-to-end."""
        import httpx

        events: list[dict[str, Any]] = []
        errors: list[str] = []
        agent_invocations = 0
        artifacts: list[str] = []

        start_time = time.monotonic()

        try:
            # 1. Create session
            resp = httpx.post(
                f"{self.base_url}/api/session",
                json={
                    "persona": scenario.persona,
                    "course_id": scenario.course_id,
                },
                timeout=10,
            )
            resp.raise_for_status()
            session_data = resp.json()
            session_id = session_data.get("session_id", session_data.get("id"))

            # 2. Process each user turn
            for turn in scenario.user_turns:
                approval_index = 0

                # Post user message
                resp = httpx.post(
                    f"{self.base_url}/api/converse",
                    json={
                        "session_id": session_id,
                        "message": turn.message,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                turn_data = resp.json()
                turn_id = turn_data.get("turn_id", turn_data.get("id"))

                # Read SSE stream
                with httpx.stream(
                    "GET",
                    f"{self.base_url}/api/stream",
                    params={"session_id": session_id, "turn_id": turn_id},
                    timeout=httpx.Timeout(
                        connect=10,
                        read=scenario.expected.max_wall_time_ms / 1000 + 5,
                        write=10,
                        pool=10,
                    ),
                ) as stream:
                    for line in stream.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
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
                                httpx.post(
                                    f"{self.base_url}/api/approval",
                                    json={
                                        "session_id": session_id,
                                        "turn_id": turn_id,
                                        "request_id": event.get("payload", {}).get("request_id"),
                                        "decision": approval.decision,
                                        "edits": approval.edits,
                                    },
                                    timeout=10,
                                )
                                approval_index += 1
                            else:
                                errors.append(
                                    f"Unexpected approval_request (no scripted approval at index {approval_index})"
                                )

                        if event_type in ("final", "error"):
                            break

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
