from __future__ import annotations

import pytest

from src.agents import eval_harness
from src.agents.eval_harness import (
    AGENT_NAMES,
    MIN_CASES_PER_AGENT,
    PLANNED_AGENT_NAMES,
    load_eval_cases,
    run_validation,
    validate_cases,
)


def _case(case_id: str) -> dict:
    return {"id": case_id, "inputs": {}, "expected": {"assertions": []}}


def _cases(n: int) -> list[dict]:
    return [_case(f"c{i}") for i in range(n)]


def test_valid_cases_have_no_errors():
    assert validate_cases("x", _cases(MIN_CASES_PER_AGENT)) == []


def test_too_few_cases_is_an_error():
    errors = validate_cases("x", _cases(MIN_CASES_PER_AGENT - 1))
    assert any("need >=" in e for e in errors)


def test_missing_fields_are_reported():
    cases = _cases(MIN_CASES_PER_AGENT)
    cases[0] = {"id": "c0"}
    errors = validate_cases("x", cases)
    assert any("missing fields ['expected', 'inputs']" in e for e in errors)
    assert any("expected.assertions missing" in e for e in errors)


def test_duplicate_ids_are_reported():
    cases = _cases(MIN_CASES_PER_AGENT)
    cases[1]["id"] = "c0"
    assert any("duplicate case id 'c0'" in e for e in validate_cases("x", cases))


def test_null_expected_is_reported_not_raised():
    cases = _cases(MIN_CASES_PER_AGENT)
    cases[0]["expected"] = None
    assert any("expected.assertions missing" in e for e in validate_cases("x", cases))


def test_load_eval_cases_raises_for_unknown_agent():
    with pytest.raises(FileNotFoundError):
        load_eval_cases("no_such_agent")


def test_run_validation_fails_when_cases_are_missing(capsys):
    assert run_validation(["no_such_agent"]) is False
    assert "No eval_cases.yaml" in capsys.readouterr().err


def test_run_validation_defaults_to_live_agents(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(eval_harness, "load_eval_cases", lambda n: seen.append(n) or _cases(5))
    assert run_validation() is True
    assert seen == AGENT_NAMES
    assert not set(seen) & set(PLANNED_AGENT_NAMES)


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_live_agent_eval_cases_are_valid(name: str):
    assert validate_cases(name, load_eval_cases(name)) == []
