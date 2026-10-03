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


def test_recordings_are_tracked_but_misses_and_partial_writes_are_not():
    assert not _ignored(f"{FIXTURES}/recordings/abc.json")
    assert not _ignored(f"{FIXTURES}/recordings/abc.2.json")
    assert _ignored(f"{FIXTURES}/recordings/misses/abc.json")
    assert _ignored(f"{FIXTURES}/recordings/abc.json.tmp")


@pytest.mark.parametrize("name", ["README.md", "compose.yaml", "run-live-e2e"])
def test_fixture_tooling_stays_tracked(name):
    assert not _ignored(f"{FIXTURES}/{name}")


def test_e2e_live_replay_runs_on_push_and_pr_from_committed_recordings():
    ci = yaml.safe_load((REPO / ".github/workflows/ci.yaml").read_text())
    # PyYAML reads the bare `on:` key as boolean True.
    triggers = ci.get("on", ci.get(True))
    job = ci["jobs"]["e2e-live-replay"]
    assert {"push", "pull_request"} <= set(triggers)
    assert "if" not in job
    assert "continue-on-error" not in job
    assert not [s for s in job["steps"] if str(s.get("uses", "")).startswith(
        "actions/download-artifact")]
    assert any("run-live-e2e replay" in str(s.get("run", "")) for s in job["steps"])


def test_committed_recordings_exist():
    assert list((REPO / FIXTURES / "recordings").glob("*.json"))


def _overlay() -> dict:
    return yaml.safe_load((REPO / FIXTURES / "compose.yaml").read_text())


def test_overlay_pins_lms_as_of_for_seed_engine_and_every_mcp_server():
    base = yaml.safe_load((REPO / "docker-compose.yaml").read_text())["services"]
    pinned = {"orchestrator", "db-seed"} | {name for name in base if name.startswith("mcp-")}
    services = _overlay()["services"]
    for name in sorted(pinned):
        assert services[name]["environment"]["LMS_AS_OF"] == "${LMS_AS_OF:-2026-10-15}", name


def test_run_live_e2e_defaults_lms_as_of_to_the_overlay_value():
    script = (REPO / FIXTURES / "run-live-e2e").read_text()
    default = _overlay()["services"]["orchestrator"]["environment"]["LMS_AS_OF"]
    assert f'export LMS_AS_OF="{default}"' in script


def test_fixture_overlay_fixes_the_pseudonym_salt():
    env = _overlay()["services"]["orchestrator"]["environment"]
    assert env["PII_PSEUDONYM_SALT"] == "llm-fixtures"


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
