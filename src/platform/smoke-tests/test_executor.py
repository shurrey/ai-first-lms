#!/usr/bin/env python3
"""Tests for the scenario executor: loading, validation, and mock run."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.platform.scenarios.models import Scenario, UserTurn, ExpectedOutcome, ApprovalAction
from src.platform.scenarios.executor import load_scenario, load_all_scenarios


def test_load_scenario():
    """Test loading a scenario from YAML."""
    scenario_data = {
        "id": 1,
        "name": "Test scenario",
        "persona": "student",
        "course_id": "cs-101",
        "user_turns": [
            {"message": "Hello, can you help me?"}
        ],
        "expected": {
            "final_event": "final",
            "min_agent_invocations": 1,
            "max_wall_time_ms": 10000,
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(scenario_data, f)
        f.flush()
        scenario = load_scenario(f.name)

    assert scenario.id == 1
    assert scenario.name == "Test scenario"
    assert scenario.persona == "student"
    assert len(scenario.user_turns) == 1
    assert scenario.user_turns[0].message == "Hello, can you help me?"
    assert scenario.expected.final_event == "final"
    print("PASS: test_load_scenario")


def test_load_scenario_with_approvals():
    """Test loading a scenario with approval actions."""
    scenario_data = {
        "id": 10,
        "name": "Multi-agent with approvals",
        "persona": "faculty",
        "course_id": "cs-101",
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
            "final_event": "final",
            "artifacts_of_type": ["content_draft", "message"],
            "min_agent_invocations": 3,
            "max_wall_time_ms": 30000,
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(scenario_data, f)
        f.flush()
        scenario = load_scenario(f.name)

    assert scenario.id == 10
    assert len(scenario.user_turns[0].approvals) == 2
    assert scenario.user_turns[0].approvals[0].decision == "approve"
    assert scenario.user_turns[0].approvals[1].decision == "edit"
    assert scenario.user_turns[0].approvals[1].edits == {"tone": "formal"}
    assert "content_draft" in scenario.expected.artifacts_of_type
    print("PASS: test_load_scenario_with_approvals")


def test_load_all_scenarios():
    """Test loading multiple scenarios from a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in [3, 1, 2]:
            data = {
                "id": i,
                "name": f"Scenario {i}",
                "persona": "student",
                "course_id": "cs-101",
                "user_turns": [{"message": f"Message {i}"}],
                "expected": {"final_event": "final"},
            }
            with open(Path(tmpdir) / f"{i:02d}-test.yaml", "w") as f:
                yaml.dump(data, f)

        scenarios = load_all_scenarios(tmpdir)
        assert len(scenarios) == 3
        assert scenarios[0].id == 1
        assert scenarios[1].id == 2
        assert scenarios[2].id == 3
        print("PASS: test_load_all_scenarios")


def test_model_validation():
    """Test that models validate correctly."""
    # Valid scenario
    s = Scenario(
        id=1,
        name="Test",
        persona="student",
        course_id="cs-101",
        user_turns=[UserTurn(message="Hi")],
        expected=ExpectedOutcome(),
    )
    assert s.expected.final_event == "final"
    assert s.expected.max_wall_time_ms == 30000

    # Valid approval
    a = ApprovalAction(decision="approve")
    assert a.edits is None

    print("PASS: test_model_validation")


if __name__ == "__main__":
    test_load_scenario()
    test_load_scenario_with_approvals()
    test_load_all_scenarios()
    test_model_validation()
    print("\nAll executor tests passed!")
