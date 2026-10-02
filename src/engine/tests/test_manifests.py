"""Tests for manifest loader and validator."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from engine.manifests import AgentManifest, ManifestRegistry, load_manifests


def test_load_real_manifests():
    """Ten routable agents, the background learning_analyst, and planned agents."""
    registry = load_manifests()
    live = [a for a in registry.list_agents() if registry.get_manifest(a).status != "planned"]
    assert len(live) == 11
    assert registry.get_manifest("feedback").status == "planned"
    agents = registry.list_agents()
    assert "tutor" in agents
    assert "communication" in agents
    assert "learning_analyst" in agents


def test_get_manifest():
    registry = load_manifests()
    tutor = registry.get_manifest("tutor")
    assert tutor.name == "tutor"
    assert "student" in tutor.persona_scope
    assert len(tutor.mcp_tools) > 0


def test_get_manifest_unknown_raises():
    registry = load_manifests()
    with pytest.raises(KeyError, match="Unknown agent"):
        registry.get_manifest("nonexistent_agent")


def test_agents_for_persona():
    registry = load_manifests()
    student_agents = registry.agents_for_persona("student")
    names = [a.name for a in student_agents]
    assert "tutor" in names
    assert "grading_assistant" not in names  # faculty only


def test_validates_required_fields():
    """Manifest with missing required fields should fail validation."""
    bad_yaml = {
        "agents": [
            {"name": "bad_agent"}
            # missing persona_scope
        ]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(bad_yaml, f)
        f.flush()
        with pytest.raises(Exception):
            load_manifests(f.name)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_manifests("/nonexistent/path/manifest.yaml")


def test_empty_agents_raises():
    empty_yaml = {"agents": []}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(empty_yaml, f)
        f.flush()
        with pytest.raises(ValueError, match="No agents found"):
            load_manifests(f.name)


def test_manifest_fields_populated():
    """Check that key fields from the contract are properly populated."""
    registry = load_manifests()
    grading = registry.get_manifest("grading_assistant")
    assert grading.requires_human_approval is True
    assert "display_name" in grading.requires_pii
    assert grading.model == "claude-sonnet-4-6"

    comm = registry.get_manifest("communication")
    assert comm.model == "claude-haiku-4-5-20251001"


def test_default_path_found_in_container_layout(tmp_path, monkeypatch):
    """The image puts the engine at /app/engine and contracts at /app/contracts."""
    import importlib.util
    import shutil
    import sys

    repo = Path(__file__).resolve().parents[3]
    (tmp_path / "engine").mkdir()
    (tmp_path / "contracts").mkdir()
    shutil.copy(repo / "src" / "engine" / "manifests.py", tmp_path / "engine" / "manifests.py")
    shutil.copy(repo / "contracts" / "agent-manifests.yaml", tmp_path / "contracts")

    spec = importlib.util.spec_from_file_location("container_manifests", tmp_path / "engine" / "manifests.py")
    module = importlib.util.module_from_spec(spec)
    # Pydantic resolves postponed annotations through sys.modules.
    monkeypatch.setitem(sys.modules, "container_manifests", module)
    spec.loader.exec_module(module)
    assert "tutor" in module.load_manifests().list_agents()
