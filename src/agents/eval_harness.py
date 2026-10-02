"""Eval harness: loads and validates the canned eval cases for each sub-agent.

Agent names come from the local manifest copies (src/agents/<name>/manifest.yaml),
which the contract checker keeps equal to contracts/agent-manifests.yaml.

Usage:
    python -m src.agents.eval_harness                # validate all live agents
    python -m src.agents.eval_harness tutor          # validate one agent
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

AGENTS_DIR = Path(__file__).parent

REQUIRED_CASE_FIELDS = {"id", "inputs", "expected"}
MIN_CASES_PER_AGENT = 5


def load_manifests() -> dict[str, dict]:
    """Return each local manifest's ``agent`` entry, keyed by agent name."""
    manifests: dict[str, dict] = {}
    for path in sorted(AGENTS_DIR.glob("*/manifest.yaml")):
        agent = yaml.safe_load(path.read_text())["agent"]
        manifests[agent["name"]] = agent
    return manifests


def is_planned(agent: dict) -> bool:
    return agent.get("status") == "planned"


_MANIFESTS = load_manifests()
AGENT_NAMES = [name for name, agent in _MANIFESTS.items() if not is_planned(agent)]
PLANNED_AGENT_NAMES = [name for name, agent in _MANIFESTS.items() if is_planned(agent)]


def eval_cases_path(agent_name: str) -> Path:
    return AGENTS_DIR / agent_name / "tests" / "eval_cases.yaml"


def load_eval_cases(agent_name: str) -> list[dict]:
    """Load eval cases for an agent. Raises FileNotFoundError if it has none."""
    path = eval_cases_path(agent_name)
    if not path.exists():
        raise FileNotFoundError(f"No eval_cases.yaml for {agent_name} at {path}")
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("cases", [])


def validate_cases(agent_name: str, cases: list[dict]) -> list[str]:
    """Validate eval case structure. Returns a list of errors (empty = valid)."""
    errors: list[str] = []

    if len(cases) < MIN_CASES_PER_AGENT:
        errors.append(
            f"{agent_name}: only {len(cases)} cases, need >= {MIN_CASES_PER_AGENT}"
        )

    seen_ids: set[str] = set()
    for i, case in enumerate(cases):
        missing = REQUIRED_CASE_FIELDS - set(case.keys())
        if missing:
            errors.append(f"{agent_name} case {i}: missing fields {sorted(missing)}")

        case_id = case.get("id", f"<unnamed-{i}>")
        if case_id in seen_ids:
            errors.append(f"{agent_name}: duplicate case id '{case_id}'")
        seen_ids.add(case_id)

        expected = case.get("expected") or {}
        if "assertions" not in expected:
            errors.append(f"{agent_name} case '{case_id}': expected.assertions missing")

    return errors


def run_validation(agent_names: list[str] | None = None) -> bool:
    """Validate eval cases for the given agents (default: all live agents)."""
    names = agent_names or AGENT_NAMES
    all_errors: list[str] = []
    total = 0

    for name in names:
        try:
            cases = load_eval_cases(name)
        except FileNotFoundError as exc:
            all_errors.append(str(exc))
            continue
        total += len(cases)
        all_errors.extend(validate_cases(name, cases))

    if all_errors:
        for err in all_errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        return False

    print(f"OK: {len(names)} agents, {total} eval cases validated.")
    return True


if __name__ == "__main__":
    agents = sys.argv[1:] if len(sys.argv) > 1 else None
    ok = run_validation(agents)
    sys.exit(0 if ok else 1)
