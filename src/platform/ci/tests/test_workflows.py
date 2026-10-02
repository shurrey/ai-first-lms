from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[4] / ".github" / "workflows").glob("*.y*ml"))
SECRET_ENV = ("SEED_DEMO_PASSWORD", "ANTHROPIC_API_KEY")


def _env_maps(node: Any):
    if isinstance(node, dict):
        if isinstance(node.get("env"), dict):
            yield node["env"]
        for value in node.values():
            yield from _env_maps(value)
    elif isinstance(node, list):
        for item in node:
            yield from _env_maps(item)


def test_workflows_are_found():
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_hardcodes_a_secret(path):
    for env in _env_maps(yaml.safe_load(path.read_text())):
        for name in SECRET_ENV:
            if name in env:
                assert str(env[name]).startswith("${{"), f"{path.name}: {name} is a literal"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_job_using_the_demo_password_generates_it(path):
    jobs = yaml.safe_load(path.read_text()).get("jobs", {})
    for name, job in jobs.items():
        text = yaml.safe_dump(job)
        if "SEED_DEMO_PASSWORD" in text or "compose" in text:
            runs = [s.get("run", "") for s in job.get("steps", [])]
            assert any("SEED_DEMO_PASSWORD=" in r and "GITHUB_ENV" in r for r in runs), name


def test_ci_concurrency_keeps_manual_runs_apart_from_push_runs():
    ci = yaml.safe_load((WORKFLOWS[0].parent / "ci.yaml").read_text())
    group = ci["concurrency"]["group"]
    assert "github.event_name" in group and "github.ref" in group
