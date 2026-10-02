"""Run with: uv run pytest src/platform/ci/tests -q (not in the default testpaths)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_contracts.py"
_spec = importlib.util.spec_from_file_location("check_contracts", _SCRIPT)
check_contracts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_contracts)


def _doc(tool: str, roles: str, mutates: str = "true", change: str = "") -> str:
    lines = [
        "## `content` (port 7001)", "", f"### `{tool}`",
        f"- Mutates: {mutates}", "- Requires approval: false", f"- Allowed roles: {roles}",
    ]
    if change:
        lines.append(change)
    return "\n".join(lines) + "\n"


def test_the_contract_limits_shared_content_writers():
    assert check_contracts.check_shared_content_writers() == []


def test_the_contract_never_lets_an_advisor_or_student_save_a_draft_or_a_skill():
    documented = check_contracts.documented_tools()
    assert "advisor" not in documented["content.save_draft"]["roles"]
    assert "student" not in documented["content.save_draft"]["roles"]
    assert "advisor" not in documented["content.save_skill"]["roles"]
    assert "student" not in documented["content.save_skill"]["roles"]


@pytest.mark.parametrize("tool,roles", [
    ("content.save_skill", "`student`, `faculty`, `instructional_designer`"),
    ("content.save_skill", "`faculty`, `advisor`"),
    ("content.save_draft", "`student`, `faculty`, `instructional_designer`, `advisor`"),
    ("content.save_draft", "`student` (own drafts), `faculty`, `instructional_designer`"),
])
def test_a_widened_shared_content_writer_is_reported(tool, roles):
    errors = check_contracts.check_shared_content_writers(_doc(tool, roles))
    assert len(errors) == 1 and tool in errors[0]


def test_a_qualified_role_counts_and_names_inside_the_qualifier_do_not():
    roles = "`student` (own drafts, not `advisor` ones), `faculty`"
    assert check_contracts._roles(roles) == frozenset({"student", "faculty"})


def test_a_shared_content_writer_must_be_marked_mutating():
    errors = check_contracts.check_shared_content_writers(
        _doc("content.save_skill", "`faculty`", mutates="false"))
    assert errors and "Mutates" in errors[0]


def test_only_an_approval_change_line_excuses_an_approval_mismatch():
    roles_only = _doc("content.save_skill", "`faculty`",
                      change="- Change: T-C-107 — removes `advisor`.")
    approval = _doc("content.save_skill", "`faculty`",
                    change="- Change: T-C-105 — `requires_approval` false → true.")
    tool = "content.save_skill"
    assert check_contracts.documented_tools(roles_only)[tool]["approval_change"] is False
    assert check_contracts.documented_tools(approval)[tool]["approval_change"] is True
