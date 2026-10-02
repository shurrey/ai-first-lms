"""Per-tool "Allowed roles" and "Requires approval" from contracts/mcp-tools.md (§5.2).

Only backticked names on a `- Allowed roles:` line are roles; a parenthesised qualifier
is kept as text and not enforced. Bare words such as "engine-internal" grant nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PLANNED_HEADING = "## Planned (Round 2)"
NOT_IMPLEMENTED_HEADING = "## Not implemented"

_TOOL_HEADING = re.compile(r"(?m)^###\s+`([^`]+)`")
_ROLES_LINE = re.compile(r"(?m)^- Allowed roles:\s*(.*)$")
_APPROVAL_LINE = re.compile(r"(?m)^- Requires approval:\s*(true|false)\b")
_INPUT_LINE = re.compile(r"(?m)^- Input:\s*(.*)$")
_INPUT_KEY = re.compile(r"\b([a-z_][a-z0-9_]*)\??\s*:")
_ROLE_ENTRY = re.compile(r"`([a-z_]+)`(?:\s*\(([^)]*)\))?")


@dataclass(frozen=True)
class ToolRoles:
    tool: str
    allowed_roles: frozenset[str]
    qualifiers: dict[str, str] = field(default_factory=dict)
    requires_approval: bool = False
    input_keys: frozenset[str] = frozenset()  # every property name on the `- Input:` line


def parse_allowed_roles(line: str) -> tuple[frozenset[str], dict[str, str]]:
    """Roles and their qualifiers from the text after `- Allowed roles:`."""
    roles: set[str] = set()
    qualifiers: dict[str, str] = {}
    for match in _ROLE_ENTRY.finditer(line):
        prefix = line[:match.start()]
        if prefix.count("(") != prefix.count(")"):
            continue  # a backticked name inside another entry's qualifier
        role, qualifier = match.group(1), match.group(2)
        roles.add(role)
        if qualifier:
            qualifiers[role] = qualifier.strip()
    return frozenset(roles), qualifiers


def parse_tool_roles(text: str) -> dict[str, ToolRoles]:
    """Served tools only: the Planned and Not implemented sections are ignored."""
    served = text.split(NOT_IMPLEMENTED_HEADING, 1)[0].split(PLANNED_HEADING, 1)[0]
    headings = list(_TOOL_HEADING.finditer(served))
    tools: dict[str, ToolRoles] = {}
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(served)
        block = served[heading.end():end]
        line = _ROLES_LINE.search(block)
        roles, qualifiers = parse_allowed_roles(line.group(1)) if line else (frozenset(), {})
        approval = _APPROVAL_LINE.search(block)
        inputs = _INPUT_LINE.search(block)
        name = heading.group(1)
        tools[name] = ToolRoles(
            name, roles, qualifiers,
            requires_approval=bool(approval and approval.group(1) == "true"),
            input_keys=frozenset(_INPUT_KEY.findall(inputs.group(1))) if inputs else frozenset(),
        )
    return tools


def load_tool_roles(path: str | Path | None = None) -> dict[str, ToolRoles]:
    """Defaults to the nearest contracts/mcp-tools.md above this file; raises if missing."""
    if path is None:
        here = Path(__file__).resolve()
        candidates = [d / "contracts" / "mcp-tools.md" for d in here.parents]
        path = next((c for c in candidates if c.exists()), candidates[-1])
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Tool contract not found: {path}")
    tools = parse_tool_roles(path.read_text())
    if not tools:
        raise ValueError(f"No tools found in {path}")
    return tools
