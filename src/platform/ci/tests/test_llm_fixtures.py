from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
FIXTURES = "src/platform/llm-fixtures"


def _ignored(rel: str) -> bool:
    # --no-index: answer from .gitignore alone, whether or not the path is tracked.
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=REPO)
    assert result.returncode in (0, 1), result
    return result.returncode == 0


def test_recordings_are_git_ignored():
    assert _ignored(f"{FIXTURES}/recordings/abc.json")
    assert _ignored(f"{FIXTURES}/recordings/misses/abc.json")


@pytest.mark.parametrize("name", ["README.md", "compose.yaml", "run-live-e2e"])
def test_fixture_tooling_stays_tracked(name):
    assert not _ignored(f"{FIXTURES}/{name}")


def test_e2e_live_replay_runs_only_on_manual_dispatch():
    ci = yaml.safe_load((REPO / ".github/workflows/ci.yaml").read_text())
    # PyYAML reads the bare `on:` key as boolean True.
    triggers = ci.get("on", ci.get(True))
    job = ci["jobs"]["e2e-live-replay"]
    assert "workflow_dispatch" in triggers
    assert job.get("if") == "github.event_name == 'workflow_dispatch'"
    downloads = [s for s in job["steps"] if str(s.get("uses", "")).startswith(
        "actions/download-artifact")]
    assert downloads and downloads[0]["with"]["path"] == f"{FIXTURES}/recordings"


def test_fixture_overlay_confirms_fixture_mode_to_the_engine():
    # The engine refuses record/replay unless LLM_FIXTURE_ALLOW=1 (src/engine/llm_fixture.py).
    overlay = yaml.safe_load((REPO / FIXTURES / "compose.yaml").read_text())
    env = overlay["services"]["orchestrator"]["environment"]
    assert str(env["LLM_FIXTURE_ALLOW"]) == "1"


def test_base_compose_passes_fixture_allow_through_defaulting_off():
    base = yaml.safe_load((REPO / "docker-compose.yaml").read_text())
    env = base["services"]["orchestrator"]["environment"]
    assert env["LLM_FIXTURE_ALLOW"] == "${LLM_FIXTURE_ALLOW:-}"
    assert env["LLM_FIXTURE_MODE"] == "${LLM_FIXTURE_MODE:-off}"
