"""Manifest loader and validator for contracts/agent-manifests.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AgentManifest(BaseModel):
    """Typed representation of a single agent manifest."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    persona_scope: list[str]
    model: str = "claude-sonnet-4-6"
    requires_pii: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    mcp_tools: list[str] = Field(default_factory=list)
    composable_with: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    example_queries: list[str] = Field(default_factory=list)


class ManifestRegistry:
    """In-memory registry of agent manifests. Loaded once at startup."""

    def __init__(self, manifests: list[AgentManifest]) -> None:
        self._by_name: dict[str, AgentManifest] = {m.name: m for m in manifests}

    def get_manifest(self, agent_name: str) -> AgentManifest:
        """Look up a manifest by agent name. Raises KeyError if not found."""
        if agent_name not in self._by_name:
            raise KeyError(f"Unknown agent: {agent_name!r}")
        return self._by_name[agent_name]

    def list_agents(self) -> list[str]:
        return list(self._by_name.keys())

    def agents_for_persona(self, persona: str) -> list[AgentManifest]:
        return [m for m in self._by_name.values() if persona in m.persona_scope]

    def __len__(self) -> int:
        return len(self._by_name)


def load_manifests(path: str | Path | None = None) -> ManifestRegistry:
    """Load and validate agent manifests from a YAML file.

    Defaults to contracts/agent-manifests.yaml relative to the repo root.
    """
    if path is None:
        # Walk up from this file to find contracts/
        repo_root = Path(__file__).resolve().parent.parent.parent
        path = repo_root / "contracts" / "agent-manifests.yaml"
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "agents" not in raw:
        raise ValueError("Manifest file must contain a top-level 'agents' key")

    manifests = []
    for entry in raw["agents"]:
        manifest = AgentManifest.model_validate(entry)
        manifests.append(manifest)

    if not manifests:
        raise ValueError("No agents found in manifest file")

    return ManifestRegistry(manifests)
