from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "language_lint.py"
_spec = importlib.util.spec_from_file_location("language_lint", _SCRIPT)
lint = importlib.util.module_from_spec(_spec)
# dataclasses look the module up in sys.modules while the class body runs.
sys.modules["language_lint"] = lint
_spec.loader.exec_module(lint)

TERMS = lint.terms_from_yaml({
    "avoid": ["companion", "knows", "Thinking", "AI Tutor", "I'm happy to"],
    "use": {"Thinking": "Working…"},
    "case_sensitive": ["Thinking"],
})


def _tsx_terms(source: str) -> list[str]:
    return [h.term.text for h in lint.lint_tsx("x.tsx", source, TERMS)]


def test_terms_parse_from_the_language_doc_yaml_block():
    md = "# Guide\n\n```yaml\navoid:\n  - buddy\n  - Thinking\nuse:\n  buddy: tool\n" \
         "case_sensitive:\n  - Thinking\n```\n"
    terms = {t.text: t for t in lint.terms_from_markdown(md)}
    assert set(terms) == {"buddy", "Thinking"}
    assert terms["buddy"].use == "tool"
    assert terms["Thinking"].pattern.search("thinking") is None


def test_falls_back_to_the_spec_table_without_a_language_doc(tmp_path):
    terms, source = lint.load_terms(tmp_path / "missing.md")
    assert "fallback" in source
    assert {"companion", "Thinking", "AI Tutor"} <= {t.text for t in terms}


def test_the_repo_language_doc_has_a_term_list():
    terms, source = lint.load_terms()
    assert "language.md" in source and terms


@pytest.mark.parametrize("source, expected", [
    ("const x = () => <span>Thinking...</span>;", ["Thinking"]),
    ('const label = "Your study companion";', ["companion"]),
    ("const t = `The AI Tutor ${name} says`;", ["AI Tutor"]),
    ('const el = <input placeholder="Ask your companion" />;', ["companion"]),
    ("const s = <p>I&apos;m happy to help</p>;", ["I'm happy to"]),
    ("const s = <p>I’m happy to help</p>;", ["I'm happy to"]),
    ("return (<div>{ok ? <b>It knows</b> : null}</div>);", ["knows"]),
])
def test_ui_copy_is_flagged(source, expected):
    assert _tsx_terms(source) == expected


@pytest.mark.parametrize("source", [
    'import { ThinkingDrawer } from "./Thinking companion";',
    "const thinking = companion.knows;",
    "function Companion() { return <ThinkingDrawer open />; }",
    "// Thinking companion\nconst a = 1;",
    "/* AI Tutor */ const a = 1;",
    "const x = <div>{/* Thinking */}</div>;",
    'const kind = step.type === "thinking";',
    'const el = <div className="companion-card" data-testid="AI Tutor" />;',
    "const f = (a: Array<string>) => a.length < 2 && b > 1;",
    "const r = /Thinking/.test(s);",
    "const s = <p>critical thinking</p>;",
    'const m = require("companion");',
])
def test_identifiers_imports_comments_and_keys_are_ignored(source):
    assert _tsx_terms(source) == []


def test_hits_report_the_line_they_are_on():
    source = "function A() {\n  return (\n    <p>\n      Thinking\n    </p>\n  );\n}\n"
    [hit] = lint.lint_tsx("a.tsx", source, TERMS)
    assert hit.line == 4 and hit.kind == "JSX text"


def test_prompts_match_whole_words_case_insensitively():
    prompt = "You are a COMPANION.\nThe student knows.\nCompanionship is fine.\n"
    hits = lint.lint_prompt("p.md", prompt, TERMS)
    assert [(h.term.text, h.line) for h in hits] == [("companion", 1), ("knows", 2)]


def test_allowlist_suppresses_only_the_matching_use(tmp_path):
    hits = lint.lint_prompt("src/agents/tutor/system_prompt.md",
                            "Check what the student knows.\nThe tool knows best.\n", TERMS)
    allow_file = tmp_path / "allow.yaml"
    allow_file.write_text(
        "entries:\n"
        "  - path: src/agents/*/system_prompt.md\n"
        "    term: knows\n"
        "    line_contains: the student knows\n"
        "    reason: Describes the student.\n"
        "  - path: src/other.md\n"
        "    term: knows\n"
        "    reason: Unused.\n"
    )
    remaining, unused = lint.apply_allowlist(hits, lint.load_allowlist(allow_file))
    assert [h.line for h in remaining] == [2]
    assert [e.path for e in unused] == ["src/other.md"]


def test_allowlist_entries_need_a_reason(tmp_path):
    allow_file = tmp_path / "allow.yaml"
    allow_file.write_text("entries:\n  - path: a.md\n    term: knows\n")
    with pytest.raises(ValueError, match="reason"):
        lint.load_allowlist(allow_file)


def test_tree_scan_covers_prompts_and_shipped_tsx_only(tmp_path):
    (tmp_path / "docs").mkdir()
    files = {
        "src/agents/a/system_prompt.md": "A study companion.",
        "src/frontend/components/A.tsx": "const a = <p>Thinking</p>;",
        "src/ultra-frontend/app/page.tsx": 'const b = "AI Tutor";',
        "src/frontend/node_modules/x/B.tsx": "const a = <p>Thinking</p>;",
        "src/frontend/components/A.test.tsx": "const a = <p>Thinking</p>;",
        "src/agents/a/notes.md": "A study companion.",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    hits = lint.lint_tree(tmp_path, TERMS)
    assert sorted(h.path for h in hits) == [
        "src/agents/a/system_prompt.md",
        "src/frontend/components/A.tsx",
        "src/ultra-frontend/app/page.tsx",
    ]


def test_main_exits_nonzero_on_a_hit(tmp_path, capsys):
    (tmp_path / "src/agents/a").mkdir(parents=True)
    (tmp_path / "src/agents/a/system_prompt.md").write_text("Your study buddy.")
    empty = tmp_path / "allow.yaml"
    empty.write_text("entries: []\n")
    assert lint.main(["--root", str(tmp_path), "--allowlist", str(empty)]) == 1
    assert "buddy" in capsys.readouterr().out


def _py_hits(source: str) -> list[tuple[str, int]]:
    return [(h.term.text, h.line) for h in lint.lint_python("src/engine/x.py", source, TERMS)]


def test_engine_prompt_constants_are_flagged_on_their_source_line():
    source = (
        'INTERPRET_SYSTEM_PROMPT = """\\\n'
        "You classify intent.\n"
        "Your study companion.\n"
        '"""\n'
        '_TOOL_USE_ADDENDUM = "It knows the tools."\n'
        "_COACHING_PROMPTS: dict[str, str] = {\n"
        '    "student": "I\'m happy to help.",\n'
        "}\n"
    )
    assert _py_hits(source) == [("companion", 3), ("knows", 5), ("I'm happy to", 7)]


def test_strings_reaching_messages_create_system_are_flagged():
    source = (
        "async def run(client, x):\n"
        '    system = load() if x else "A study companion."\n'
        '    system += " It knows."\n'
        "    await client.messages.create(model=m, system=system, messages=[])\n"
        '    await client.messages.create(system="AI Tutor", messages=[])\n'
    )
    assert sorted(_py_hits(source)) == [("AI Tutor", 5), ("companion", 2), ("knows", 3)]


def test_module_constants_referenced_by_a_prompt_constant_are_flagged():
    source = (
        'BASE = "It knows the course."\n'
        'TUTOR_PROMPT = "Hi. " + BASE\n'
    )
    assert _py_hits(source) == [("knows", 1)]


@pytest.mark.parametrize("source", [
    'LABEL = "Your study companion"',
    'def f():\n    """It knows."""\n    log.info("companion", detail="It knows")',
    'other.create(system="A study companion.")',
    'SYSTEM_PROMPT_PATH_PROMPT = "agents/companion/system_prompt.md"',
    'def f(c):\n    prompt = "companion talk"\n    c.messages.create(system=s, messages=[prompt])',
])
def test_non_prompt_python_strings_are_ignored(source):
    assert _py_hits(source) == []


def test_tree_scan_covers_engine_python_but_not_its_tests(tmp_path):
    files = {
        "src/engine/brief.py": 'BRIEF_PROMPT = "Your study buddy."',
        "src/engine/tests/test_brief.py": 'BRIEF_PROMPT = "Your study buddy."',
        "src/agents/a/agent.py": 'A_PROMPT = "Your study buddy."',
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    hits = lint.lint_tree(tmp_path, TERMS + lint.terms_from_yaml({"avoid": ["buddy"]}))
    assert [(h.path, h.kind) for h in hits] == [("src/engine/brief.py", "engine prompt")]
