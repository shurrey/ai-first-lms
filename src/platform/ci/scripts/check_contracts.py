#!/usr/bin/env python3
"""Validate contract invariants.

Checks:
1. agent-manifests.yaml parses as valid YAML
2. All MCP tool names referenced by manifests exist in mcp-tools.md
3. db-schema.sql is valid (non-empty, has CREATE statements)
4. api.openapi.yaml parses as valid YAML with required OpenAPI fields
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def check_manifests(contracts_dir: Path) -> list[str]:
    """Validate agent-manifests.yaml parses and has expected structure."""
    errors: list[str] = []
    manifest_path = contracts_dir / "agent-manifests.yaml"

    if not manifest_path.exists():
        return [f"Missing: {manifest_path}"]

    try:
        data = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as e:
        return [f"agent-manifests.yaml: YAML parse error: {e}"]

    if not isinstance(data, dict):
        return ["agent-manifests.yaml: root must be a mapping"]

    agents = data.get("agents")
    if not isinstance(agents, list):
        return ["agent-manifests.yaml: 'agents' must be a list"]

    for i, agent in enumerate(agents):
        if not isinstance(agent, dict):
            errors.append(f"agent-manifests.yaml: agents[{i}] must be a mapping")
            continue
        name = agent.get("name", f"<unnamed-{i}>")
        if "name" not in agent:
            errors.append(f"agent-manifests.yaml: agents[{i}] missing 'name'")
        if "mcp_tools" not in agent:
            errors.append(f"agent-manifests.yaml: agent '{name}' missing 'mcp_tools'")

    return errors


def extract_mcp_tool_names(contracts_dir: Path) -> set[str]:
    """Extract all tool names from mcp-tools.md (### `tool.name` headings)."""
    tools_path = contracts_dir / "mcp-tools.md"
    if not tools_path.exists():
        return set()

    text = tools_path.read_text()
    # Match ### `tool.name` patterns
    return set(re.findall(r"###\s+`([^`]+)`", text))


def check_tool_references(contracts_dir: Path) -> list[str]:
    """Verify all MCP tool names in manifests exist in mcp-tools.md."""
    errors: list[str] = []
    manifest_path = contracts_dir / "agent-manifests.yaml"

    try:
        data = yaml.safe_load(manifest_path.read_text())
    except (yaml.YAMLError, FileNotFoundError):
        return []  # Already reported in check_manifests

    known_tools = extract_mcp_tool_names(contracts_dir)

    # graph.* tools are from the shared graph library, not a separate MCP server
    # They may not be listed in mcp-tools.md
    graph_tools = {t for t in known_tools if t.startswith("graph.")}

    for agent in data.get("agents", []):
        name = agent.get("name", "<unnamed>")
        for tool in agent.get("mcp_tools", []):
            if tool.startswith("graph."):
                continue  # graph tools are a shared library, not in mcp-tools.md
            if tool not in known_tools:
                errors.append(f"Agent '{name}' references unknown tool: {tool}")

    return errors


def check_db_schema(contracts_dir: Path) -> list[str]:
    """Verify db-schema.sql exists and has CREATE statements."""
    schema_path = contracts_dir / "db-schema.sql"
    if not schema_path.exists():
        return [f"Missing: {schema_path}"]

    text = schema_path.read_text()
    if not text.strip():
        return ["db-schema.sql: file is empty"]

    if "CREATE TABLE" not in text.upper():
        return ["db-schema.sql: no CREATE TABLE statements found"]

    return []


def check_openapi(contracts_dir: Path) -> list[str]:
    """Verify api.openapi.yaml is valid YAML with required OpenAPI fields."""
    api_path = contracts_dir / "api.openapi.yaml"
    if not api_path.exists():
        return [f"Missing: {api_path}"]

    try:
        data = yaml.safe_load(api_path.read_text())
    except yaml.YAMLError as e:
        return [f"api.openapi.yaml: YAML parse error: {e}"]

    if not isinstance(data, dict):
        return ["api.openapi.yaml: root must be a mapping"]

    errors: list[str] = []
    if "openapi" not in data:
        errors.append("api.openapi.yaml: missing 'openapi' version field")
    if "info" not in data:
        errors.append("api.openapi.yaml: missing 'info' field")
    if "paths" not in data:
        errors.append("api.openapi.yaml: missing 'paths' field")

    return errors


def main() -> int:
    contracts_dir = Path("contracts")
    if not contracts_dir.exists():
        print("ERROR: contracts/ directory not found")
        return 1

    all_errors: list[str] = []
    all_errors.extend(check_manifests(contracts_dir))
    all_errors.extend(check_tool_references(contracts_dir))
    all_errors.extend(check_db_schema(contracts_dir))
    all_errors.extend(check_openapi(contracts_dir))

    if all_errors:
        print(f"Contract invariant check FAILED ({len(all_errors)} errors):")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("Contract invariant check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
