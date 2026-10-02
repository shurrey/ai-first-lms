"""Permission guardrail — role × agent/tool access control (SPEC §14.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from engine.manifests import AgentManifest, ManifestRegistry

logger = logging.getLogger(__name__)


@dataclass
class PermissionCheck:
    allowed: bool
    reason: str = ""


@dataclass
class PermissionMatrix:
    """Permission matrix derived from agent manifests.

    Maps persona → set of allowed agent names and MCP tools.
    """

    _agent_permissions: dict[str, set[str]] = field(default_factory=dict)
    _tool_permissions: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_registry(cls, registry: ManifestRegistry) -> PermissionMatrix:
        """Build permission matrix from the manifest registry."""
        matrix = cls()
        for agent_name in registry.list_agents():
            manifest = registry.get_manifest(agent_name)
            if manifest.status == "planned":
                continue
            for persona in manifest.persona_scope:
                # Allow agent access
                if persona not in matrix._agent_permissions:
                    matrix._agent_permissions[persona] = set()
                matrix._agent_permissions[persona].add(agent_name)

                # Allow tool access for tools this agent uses
                if persona not in matrix._tool_permissions:
                    matrix._tool_permissions[persona] = set()
                matrix._tool_permissions[persona].update(manifest.mcp_tools)

        return matrix

    def check_agent(self, persona: str, agent_name: str) -> PermissionCheck:
        """Check if a persona can invoke a specific agent."""
        allowed_agents = self._agent_permissions.get(persona, set())
        if agent_name in allowed_agents:
            return PermissionCheck(allowed=True)
        return PermissionCheck(
            allowed=False,
            reason=f"Persona '{persona}' is not allowed to use agent '{agent_name}'",
        )

    def check_tool(self, persona: str, tool_name: str) -> PermissionCheck:
        """Check if a persona can access a specific MCP tool."""
        allowed_tools = self._tool_permissions.get(persona, set())
        if tool_name in allowed_tools:
            return PermissionCheck(allowed=True)
        return PermissionCheck(
            allowed=False,
            reason=f"Persona '{persona}' is not allowed to use tool '{tool_name}'",
        )

    def allowed_agents(self, persona: str) -> set[str]:
        return self._agent_permissions.get(persona, set())

    def allowed_tools(self, persona: str) -> set[str]:
        return self._tool_permissions.get(persona, set())
