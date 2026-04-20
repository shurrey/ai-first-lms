"""Eval harness — loads and validates eval cases for all sub-agents.

Usage:
    python -m src.agents.eval_harness                # validate all
    python -m src.agents.eval_harness tutor           # validate one agent
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

AGENTS_DIR = Path(__file__).parent
AGENT_NAMES = [
    "tutor",
    "content_generator",
    "assessment",
    "grading_assistant",
    "early_alert",
    "advising",
    "accessibility",
    "engagement_analyst",
    "communication",
    "course_architect",
]

REQUIRED_CASE_FIELDS = {"id", "inputs", "expected"}
MIN_CASES_PER_AGENT = 5


def load_eval_cases(agent_name: str) -> list[dict]:
    """Load eval cases for a given agent."""
    path = AGENTS_DIR / agent_name / "tests" / "eval_cases.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No eval_cases.yaml for {agent_name} at {path}")
    data = yaml.safe_load(path.read_text())
    return data.get("cases", [])


def validate_cases(agent_name: str, cases: list[dict]) -> list[str]:
    """Validate eval cases structure. Returns a list of errors (empty = valid)."""
    errors: list[str] = []

    if len(cases) < MIN_CASES_PER_AGENT:
        errors.append(
            f"{agent_name}: only {len(cases)} cases, need >= {MIN_CASES_PER_AGENT}"
        )

    seen_ids: set[str] = set()
    for i, case in enumerate(cases):
        missing = REQUIRED_CASE_FIELDS - set(case.keys())
        if missing:
            errors.append(f"{agent_name} case {i}: missing fields {missing}")

        case_id = case.get("id", f"<unnamed-{i}>")
        if case_id in seen_ids:
            errors.append(f"{agent_name}: duplicate case id '{case_id}'")
        seen_ids.add(case_id)

        expected = case.get("expected", {})
        if "assertions" not in expected:
            errors.append(f"{agent_name} case '{case_id}': expected.assertions missing")

    return errors


def run_validation(agent_names: list[str] | None = None) -> bool:
    """Validate eval cases for the given agents (or all). Returns True if valid."""
    names = agent_names or AGENT_NAMES
    all_errors: list[str] = []

    for name in names:
        try:
            cases = load_eval_cases(name)
        except FileNotFoundError as exc:
            all_errors.append(str(exc))
            continue
        all_errors.extend(validate_cases(name, cases))

    if all_errors:
        for err in all_errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        return False

    total = sum(len(load_eval_cases(n)) for n in names)
    print(f"OK: {len(names)} agents, {total} eval cases validated.")
    return True


if __name__ == "__main__":
    agents = sys.argv[1:] if len(sys.argv) > 1 else None
    ok = run_validation(agents)
    sys.exit(0 if ok else 1)
