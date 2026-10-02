"""Process-wide contract registries (manifests, permission matrix, tool roles), loaded once."""

from __future__ import annotations

from functools import lru_cache

from engine.guardrails.permissions import PermissionMatrix
from engine.guardrails.tool_roles import ToolRoles, load_tool_roles
from engine.manifests import ManifestRegistry, load_manifests


@lru_cache(maxsize=1)
def get_manifest_registry() -> ManifestRegistry:
    """Raises if contracts/agent-manifests.yaml is missing or invalid (fail closed)."""
    return load_manifests()


@lru_cache(maxsize=1)
def get_permission_matrix() -> PermissionMatrix:
    return PermissionMatrix.from_registry(get_manifest_registry())


@lru_cache(maxsize=1)
def get_tool_roles() -> dict[str, ToolRoles]:
    """Raises if contracts/mcp-tools.md is missing or lists no tools (fail closed)."""
    return load_tool_roles()
