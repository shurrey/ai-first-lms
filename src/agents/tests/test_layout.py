"""Each agent directory holds data the runner and evals consume, and nothing else."""

from __future__ import annotations

import re

import pytest
import yaml

from src.agents.eval_harness import (
    AGENT_NAMES,
    AGENTS_DIR,
    PLANNED_AGENT_NAMES,
    eval_cases_path,
    load_manifests,
)

CONTRACT_MANIFESTS = AGENTS_DIR.parents[1] / "contracts" / "agent-manifests.yaml"


def _contract_agents() -> dict[str, dict]:
    data = yaml.safe_load(CONTRACT_MANIFESTS.read_text())
    return {agent["name"]: agent for agent in data["agents"]}


def test_local_manifests_cover_every_contract_agent():
    assert set(load_manifests()) == set(_contract_agents())


def test_live_and_planned_split_matches_contract_status():
    contract = _contract_agents()
    expected_planned = {n for n, a in contract.items() if a.get("status") == "planned"}
    assert set(PLANNED_AGENT_NAMES) == expected_planned
    assert set(AGENT_NAMES) == set(contract) - expected_planned


def test_background_learning_analyst_is_a_live_agent():
    assert "learning_analyst" in AGENT_NAMES


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_live_agent_has_prompt_manifest_and_evals(name: str):
    agent_dir = AGENTS_DIR / name
    assert (agent_dir / "manifest.yaml").is_file()
    prompt = agent_dir / "system_prompt.md"
    assert prompt.is_file()
    assert prompt.read_text().strip()
    assert eval_cases_path(name).is_file()


@pytest.mark.parametrize("name", PLANNED_AGENT_NAMES)
def test_planned_agent_has_manifest_and_no_live_tools(name: str):
    # A planned agent's prompt and evals arrive with the task that builds it.
    agent = load_manifests()[name]
    assert (AGENTS_DIR / name / "manifest.yaml").is_file()
    assert agent.get("mcp_tools", []) == []


def test_no_python_agent_classes():
    # The runner is the only live agent path (spec.md §5.4).
    stray = sorted(
        str(p.relative_to(AGENTS_DIR))
        for p in AGENTS_DIR.rglob("*.py")
        if p.parent != AGENTS_DIR / "tests"
        and p.name not in {"__init__.py", "eval_harness.py"}
    )
    assert stray == []



def _allowed_roles(tool: str) -> set[str]:
    text = (AGENTS_DIR.parents[1] / "contracts" / "mcp-tools.md").read_text()
    section = text.split(f"### `{tool}`", 1)[1].split("\n### ", 1)[0]
    line = next(ln for ln in section.splitlines() if ln.startswith("- Allowed roles:"))
    return set(re.findall(r"`([a-z_]+)`", line))


ROLE_LIMITED_TOOLS = (
    "content.save_draft",
    "content.save_skill",
    "content.generate_practice",
    "assessments.propose_alignment",
    "graph.subgraph_for_outcomes",
)
PROMPTED_AGENTS = sorted(p.parent.name for p in AGENTS_DIR.glob("*/system_prompt.md"))


@pytest.mark.parametrize("name", PROMPTED_AGENTS)
def test_prompt_limits_role_limited_tools_to_allowed_roles(name: str):
    # An agent serving roles the gateway refuses for these tools must tell the model so.
    agent = load_manifests()[name]
    granted = set(agent.get("mcp_tools", [])) | set(agent.get("planned_mcp_tools") or [])
    tools = [t for t in ROLE_LIMITED_TOOLS if t in granted]
    refused = {r for t in tools for r in set(agent["persona_scope"]) - _allowed_roles(t)}
    if not refused:
        return
    prompt = (AGENTS_DIR / name / "system_prompt.md").read_text()
    section = prompt.split("## Who may save", 1)
    assert len(section) == 2, f"{name} serves {sorted(refused)} but has no 'Who may save' section"
    body = section[1].split("\n## ", 1)[0]
    for role in refused | {r for t in tools for r in _allowed_roles(t)}:
        assert f"`{role}`" in body, role
    for tool in tools:
        if set(agent["persona_scope"]) - _allowed_roles(tool):
            assert f"`{tool}`" in body, tool
