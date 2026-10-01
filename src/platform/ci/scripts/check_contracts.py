#!/usr/bin/env python3
"""Validate contract invariants between contracts/ and the code that implements them.

Needs only the standard library and PyYAML: server tools and _AGENT_TOOLS are read
by AST-parsing the source, never by importing it. The migrations-vs-schema check
runs only when LMS_DATABASE_URL is set (it needs asyncpg and alembic).
Exit code 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS = REPO_ROOT / "contracts"
SERVERS_DIR = REPO_ROOT / "src" / "data_mcp" / "mcp_servers"
RUNNER = REPO_ROOT / "src" / "engine" / "agents" / "runner.py"
AGENTS_DIR = REPO_ROOT / "src" / "agents"
SCHEMA_CHECK = Path(__file__).resolve().parent / "check_schema_matches_migrations.py"
FRONTENDS = [REPO_ROOT / "src" / "frontend", REPO_ROOT / "src" / "ultra-frontend"]
FRONTEND_SUBDIRS = ("app", "components", "lib")

# Everything after this heading in mcp-tools.md lists tools that are deliberately not served.
NOT_IMPLEMENTED_HEADING = "## Not implemented"


class Skip(Exception):
    """Raised by a check that cannot run in this environment."""


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def manifest_agents() -> list[dict[str, Any]]:
    """Agent entries from agent-manifests.yaml; raises ValueError on a malformed file."""
    data = load_yaml(CONTRACTS / "agent-manifests.yaml")
    if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
        raise ValueError("agent-manifests.yaml: root must be a mapping with an 'agents' list")
    return data["agents"]


def server_tools() -> dict[str, dict[str, Any]]:
    """Map tool name -> {server, mutates, requires_approval} from every ToolDef(...) call."""
    tools: dict[str, dict[str, Any]] = {}
    for path in sorted(SERVERS_DIR.glob("*/tools.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ToolDef"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if "name" not in kw or not isinstance(kw["name"], ast.Constant):
                raise ValueError(f"{path}: ToolDef without a literal name= at line {node.lineno}")
            flags = {
                flag: ast.literal_eval(kw[flag]) if flag in kw else False
                for flag in ("mutates", "requires_approval")
            }
            tools[kw["name"].value] = {"server": path.parent.name, **flags}
    if not tools:
        raise ValueError(f"no ToolDef(name=...) found under {SERVERS_DIR}")
    return tools


def runner_agent_tools() -> dict[str, list[str]]:
    tree = ast.parse(RUNNER.read_text(), filename=str(RUNNER))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        )
        if isinstance(target, ast.Name) and target.id == "_AGENT_TOOLS" and node.value is not None:
            return ast.literal_eval(node.value)
    raise ValueError(f"{RUNNER}: no module-level _AGENT_TOOLS literal")


def documented_tools() -> dict[str, dict[str, Any]]:
    """Tools in the main sections of mcp-tools.md, with their Mutates/Requires approval lines."""
    text = (CONTRACTS / "mcp-tools.md").read_text()
    main = text.split(NOT_IMPLEMENTED_HEADING, 1)[0]
    tools: dict[str, dict[str, Any]] = {}
    for block in re.split(r"(?m)^###\s+", main)[1:]:
        m = re.match(r"`([^`]+)`", block)
        if not m:
            continue
        entry: dict[str, Any] = {}
        for field, key in (("Mutates", "mutates"), ("Requires approval", "requires_approval")):
            fm = re.search(rf"(?m)^- {field}:\s*(true|false)\b", block)
            entry[key] = None if fm is None else fm.group(1) == "true"
        entry["has_roles"] = re.search(r"(?m)^- Allowed roles:\s*\S", block) is not None
        tools[m.group(1)] = entry
    return tools


def _normalize_path(path: str) -> str:
    return re.sub(r"\{[^}/]*\}", "{}", path.rstrip("/") or "/")


def frontend_paths() -> dict[str, set[str]]:
    """Map normalized /api/... or /audio/... path -> files that reference it."""
    pattern = re.compile(r"""[`'"](?:\$\{[A-Za-z_]+\})?(/(?:api|audio)/[^`'"?#\s]*)""")
    found: dict[str, set[str]] = {}
    for root in FRONTENDS:
        for sub in FRONTEND_SUBDIRS:
            base = root / sub
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.suffix not in (".ts", ".tsx", ".js", ".jsx") or "node_modules" in path.parts:
                    continue
                for m in pattern.finditer(path.read_text(errors="replace")):
                    url = re.sub(r"\$\{[^}]*\}", "{}", m.group(1))
                    found.setdefault(_normalize_path(url), set()).add(str(path.relative_to(REPO_ROOT)))
    return found


# ---------------------------------------------------------------------------
# Checks: each returns a list of failure messages
# ---------------------------------------------------------------------------

def check_manifest_structure() -> list[str]:
    errors = []
    for i, agent in enumerate(manifest_agents()):
        if not isinstance(agent, dict):
            errors.append(f"agents[{i}] must be a mapping")
            continue
        name = agent.get("name", f"<unnamed-{i}>")
        for key in ("name", "persona_scope", "mcp_tools"):
            if key not in agent:
                errors.append(f"agent '{name}' missing '{key}'")
    return errors


def check_manifest_tools_served() -> list[str]:
    served = server_tools()
    return [
        f"agent '{a['name']}' references {tool}, which no MCP server exposes"
        for a in manifest_agents()
        for tool in a.get("mcp_tools", [])
        if tool not in served
    ]


def check_manifest_tools_documented() -> list[str]:
    documented = documented_tools()
    return [
        f"agent '{a['name']}' references {tool}, which mcp-tools.md does not document"
        for a in manifest_agents()
        for tool in a.get("mcp_tools", [])
        if tool not in documented
    ]


def check_manifests_match_runner() -> list[str]:
    runner = runner_agent_tools()
    manifests = {a["name"]: list(a.get("mcp_tools", [])) for a in manifest_agents()}
    errors = []
    for name in sorted(set(runner) - set(manifests)):
        errors.append(f"_AGENT_TOOLS has agent '{name}' with no manifest")
    for name in sorted(set(manifests) - set(runner)):
        errors.append(f"manifest agent '{name}' has no _AGENT_TOOLS entry")
    for name in sorted(set(runner) & set(manifests)):
        if manifests[name] != runner[name]:
            only_m = [t for t in manifests[name] if t not in runner[name]]
            only_r = [t for t in runner[name] if t not in manifests[name]]
            detail = f"manifest-only {only_m}, runner-only {only_r}" if only_m or only_r else "same tools, different order"
            errors.append(f"agent '{name}' mcp_tools != _AGENT_TOOLS: {detail}")
    return errors


def check_local_manifest_copies() -> list[str]:
    errors = []
    for agent in manifest_agents():
        path = AGENTS_DIR / agent["name"] / "manifest.yaml"
        rel = path.relative_to(REPO_ROOT)
        if not path.exists():
            errors.append(f"{rel} is missing")
            continue
        local = load_yaml(path)
        if local != {"version": 1, "agent": agent}:
            errors.append(f"{rel} differs from its entry in contracts/agent-manifests.yaml")
    return errors


def check_mcp_tools_doc() -> list[str]:
    served = server_tools()
    documented = documented_tools()
    errors = [f"mcp-tools.md documents {t}, which no MCP server exposes" for t in sorted(set(documented) - set(served))]
    errors += [f"{t} ({served[t]['server']} server) is missing from mcp-tools.md" for t in sorted(set(served) - set(documented))]
    for name in sorted(set(served) & set(documented)):
        doc = documented[name]
        for key in ("mutates", "requires_approval"):
            if doc[key] is None:
                errors.append(f"mcp-tools.md {name}: missing '{key}' line")
            elif doc[key] != served[name][key]:
                errors.append(f"mcp-tools.md {name}: {key}={doc[key]} but server has {served[name][key]}")
        if not doc["has_roles"]:
            errors.append(f"mcp-tools.md {name}: missing 'Allowed roles' line")
    return errors


def check_frontend_endpoints() -> list[str]:
    spec = load_yaml(CONTRACTS / "api.openapi.yaml")
    documented = {_normalize_path(p) for p in (spec.get("paths") or {})}
    return [
        f"{path} (called from {', '.join(sorted(files))}) is not in api.openapi.yaml paths"
        for path, files in sorted(frontend_paths().items())
        if path not in documented
    ]


def check_db_schema_file() -> list[str]:
    text = (CONTRACTS / "db-schema.sql").read_text()
    if not text.strip():
        return ["db-schema.sql is empty"]
    if "CREATE TABLE" not in text.upper():
        return ["db-schema.sql has no CREATE TABLE statements"]
    return []


def check_openapi_structure() -> list[str]:
    data = load_yaml(CONTRACTS / "api.openapi.yaml")
    if not isinstance(data, dict):
        return ["api.openapi.yaml: root must be a mapping"]
    return [f"api.openapi.yaml: missing '{k}'" for k in ("openapi", "info", "paths") if k not in data]


def check_migrations_match_schema() -> list[str]:
    if not os.environ.get("LMS_DATABASE_URL"):
        raise Skip("LMS_DATABASE_URL is not set")
    result = subprocess.run(
        [sys.executable, str(SCHEMA_CHECK)], capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode == 0:
        return []
    output = (result.stdout + result.stderr).strip().splitlines()
    return [f"check_schema_matches_migrations.py exited {result.returncode}"] + [f"  {line}" for line in output]


CHECKS: list[tuple[str, Callable[[], list[str]]]] = [
    ("agent-manifests.yaml structure", check_manifest_structure),
    ("manifest tools exist on a server", check_manifest_tools_served),
    ("manifest tools documented in mcp-tools.md", check_manifest_tools_documented),
    ("manifest tools == runner _AGENT_TOOLS", check_manifests_match_runner),
    ("src/agents/*/manifest.yaml == contract", check_local_manifest_copies),
    ("mcp-tools.md == server tools", check_mcp_tools_doc),
    ("frontend endpoints in api.openapi.yaml", check_frontend_endpoints),
    ("api.openapi.yaml structure", check_openapi_structure),
    ("db-schema.sql present", check_db_schema_file),
    ("migrations == db-schema.sql", check_migrations_match_schema),
]


def main() -> int:
    failed = 0
    for title, check in CHECKS:
        try:
            errors = check()
        except Skip as exc:
            print(f"SKIP  {title}: {exc}")
            continue
        except (OSError, ValueError, SyntaxError, yaml.YAMLError) as exc:
            errors = [f"could not run: {type(exc).__name__}: {exc}"]
        if errors:
            failed += 1
            print(f"FAIL  {title} ({len(errors)})")
            for err in errors:
                print(f"      - {err}")
        else:
            print(f"PASS  {title}")
    print()
    if failed:
        print(f"Contract invariant check FAILED: {failed} of {len(CHECKS)} checks")
        return 1
    print("Contract invariant check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
