"""Prompts ask for the contract artifacts the scenarios check, and name only granted tools."""

from __future__ import annotations

import re

import pytest
import yaml

from src.agents.eval_harness import (
    AGENTS_DIR,
    MIN_CASES_PER_AGENT,
    contract_artifact_types,
    load_eval_cases,
    validate_cases,
)

CONTRACT_MANIFESTS = AGENTS_DIR.parents[1] / "contracts" / "agent-manifests.yaml"

# Artifact types each agent's structured products map to (spec.md §21 scenarios).
AGENT_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "assessment": ("quiz",),
    "early_alert": ("risk_list",),
    "accessibility": ("wcag_report",),
    "course_architect": ("content_draft",),
    "content_generator": ("content_draft",),
    "communication": ("message",),
    "advising": ("degree_audit", "learning_path"),
    "engagement_analyst": ("chart",),
    "grading_assistant": ("rubric_grades",),
}

# Artifacts the engine builds from the named tool's result, so the prompt shows no block.
TOOL_BUILT: dict[tuple[str, str], str] = {
    ("advising", "degree_audit"): "sis.degree_audit",
    ("grading_assistant", "rubric_grades"): "assessments.draft_grade",
}

_TOOL_ROW = re.compile(r"^\| `[a-z_]+\.[a-z_]+`.*?\|", re.MULTILINE)
_TOOL_NAME = re.compile(r"`([a-z_]+\.[a-z_]+)`")


def _prompt(agent: str) -> str:
    return (AGENTS_DIR / agent / "system_prompt.md").read_text()


def _contract_agents() -> dict[str, dict]:
    data = yaml.safe_load(CONTRACT_MANIFESTS.read_text())
    return {agent["name"]: agent for agent in data["agents"]}


def _tool_table_names(prompt: str) -> set[str]:
    """Tool names in the first column of the prompt's markdown tool tables."""
    return {name for row in _TOOL_ROW.findall(prompt) for name in _TOOL_NAME.findall(row)}


def test_agent_artifacts_are_contract_types():
    assert {t for types in AGENT_ARTIFACTS.values() for t in types} <= contract_artifact_types()


@pytest.mark.parametrize(
    "agent, kind", [(a, t) for a, types in AGENT_ARTIFACTS.items() for t in types]
)
def test_prompt_shows_artifact_block(agent: str, kind: str):
    tool = TOOL_BUILT.get((agent, kind))
    if tool is None:
        assert f"```artifact {kind}\n{{" in _prompt(agent)
    else:
        assert f"No `{kind}` block: the system builds" in _prompt(agent)
        assert f"`{tool}` result" in _prompt(agent)


@pytest.mark.parametrize("agent", AGENT_ARTIFACTS)
def test_prompt_does_not_ask_for_a_json_reply(agent: str):
    # The runner wants a markdown reply; a JSON reply hides the artifact block.
    prompt = _prompt(agent)
    assert "Return a structured JSON object" not in prompt
    assert "```json" not in prompt


@pytest.mark.parametrize(
    "agent, kind", [(a, t) for a, types in AGENT_ARTIFACTS.items() for t in types]
)
def test_eval_cases_assert_scenario_artifact(agent: str, kind: str):
    cases = load_eval_cases(agent)
    asserting = [c for c in cases if kind in (c["expected"].get("artifact_types") or [])]
    assert asserting, f"{agent} has no eval case expecting a {kind} artifact"
    for case in asserting:
        assert {"emits_artifact": kind} in case["expected"]["assertions"]
        assert case["inputs"].get("message")


@pytest.mark.parametrize(
    "agent", sorted(p.parent.name for p in AGENTS_DIR.glob("*/system_prompt.md"))
)
def test_prompt_tool_tables_name_only_granted_tools(agent: str):
    manifest = _contract_agents()[agent]
    granted = set(manifest.get("mcp_tools", [])) | set(manifest.get("planned_mcp_tools") or [])
    assert _tool_table_names(_prompt(agent)) - granted == set()


def test_tool_table_names_reads_only_first_column():
    prompt = "| `a.b` | Use with `c.d`. |\n| `e.f`, `g.h` | x |\nSee `i.j`.\n"
    assert _tool_table_names(prompt) == {"a.b", "e.f", "g.h"}


def _cases_with(expected: dict) -> list[dict]:
    cases = [{"id": f"c{i}", "inputs": {}, "expected": {"assertions": []}}
             for i in range(MIN_CASES_PER_AGENT)]
    cases[0]["expected"].update(expected)
    return cases


def test_unknown_artifact_type_is_reported():
    errors = validate_cases("x", _cases_with({"artifact_types": ["risk_report"]}))
    assert any("not in FinalPayload: ['risk_report']" in e for e in errors)


def test_empty_artifact_types_is_reported():
    errors = validate_cases("x", _cases_with({"artifact_types": []}))
    assert any("artifact_types must be a non-empty list" in e for e in errors)


def test_contract_artifact_types_are_valid():
    assert validate_cases("x", _cases_with({"artifact_types": ["quiz", "message"]})) == []
