"""Process-wide manifest registry and permission matrix, loaded once on first use."""

from __future__ import annotations

from functools import lru_cache

from engine.guardrails.permissions import PermissionMatrix
from engine.manifests import ManifestRegistry, load_manifests


@lru_cache(maxsize=1)
def get_manifest_registry() -> ManifestRegistry:
    """Raises if contracts/agent-manifests.yaml is missing or invalid (fail closed)."""
    return load_manifests()


@lru_cache(maxsize=1)
def get_permission_matrix() -> PermissionMatrix:
    return PermissionMatrix.from_registry(get_manifest_registry())
