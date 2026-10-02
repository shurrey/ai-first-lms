"""Fail on anthropomorphic terms in agent prompts and UI copy (spec §14.2 item 5).

Scans src/**/system_prompt.md (whole file), prompt text embedded in src/engine/**/*.py
(see PythonPromptScanner), and the user-visible strings of .tsx files in both UIs: JSX
text, string and template literals, and copy-bearing JSX attributes. Identifiers, imports,
comments and machine-key strings are ignored. Terms come from the yaml block in
docs/language.md; exceptions live in language_allowlist.yaml.

Run: uv run python src/platform/ci/language_lint.py [--format github]
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import html
import os
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LANGUAGE_DOC = REPO_ROOT / "docs" / "language.md"
ALLOWLIST = Path(__file__).resolve().parent / "language_allowlist.yaml"
UI_ROOTS = ("src/frontend", "src/ultra-frontend")
PROMPT_CODE_ROOTS = ("src/engine",)
SKIP_DIRS = {
    "node_modules", ".next", "__tests__", "tests", "e2e", "test-results", "playwright-report",
}
TEST_SUFFIXES = (".test.tsx", ".spec.tsx", ".stories.tsx")

# §14.2 table, used only while docs/language.md has no yaml block.
FALLBACK_YAML = """
avoid: [companion, buddy, friend, thinks, knows, understands, believes, Thinking,
        AI Tutor, I feel, "I'm happy to"]
use:
  companion: tool, assistant tool, study tool
  buddy: tool, assistant tool, study tool
  friend: tool, assistant tool, study tool
  thinks: generates, retrieves, checks, estimates
  knows: generates, retrieves, checks, estimates
  understands: generates, retrieves, checks, estimates
  believes: generates, retrieves, checks, estimates
  Thinking: "Working… / Running: <tool>"
  AI Tutor: Tutor (AI)
  I feel: plain statements
  I'm happy to: plain statements
case_sensitive: [Thinking]
"""

# JSX attributes whose string values are never shown to a person.
NON_COPY_ATTRS = {
    "className", "class", "id", "key", "href", "src", "type", "role", "name", "htmlFor",
    "variant", "size", "ref", "style", "target", "rel", "method", "action", "autoComplete",
    "inputMode", "form", "lang", "dir", "color", "icon", "as", "mode", "side", "align",
    "aria-controls", "aria-labelledby", "aria-describedby", "aria-live", "aria-haspopup",
    "aria-current", "aria-expanded", "aria-selected", "aria-hidden", "testId", "fill",
    "stroke", "viewBox", "d", "xmlns", "strokeLinecap", "strokeLinejoin",
}
# All-lowercase strings without whitespace ("thinking", "agent-thinking") are event types,
# CSS classes or keys, not copy.
MACHINE_KEY = re.compile(r"^[a-z0-9_\-.:/#@]*$")


@dataclass(frozen=True)
class Term:
    text: str
    use: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Text:
    """A piece of checkable text and the 1-based line it starts on."""
    value: str
    line: int
    kind: str
    # Set for Python strings, whose value lines need not match source lines (escapes, `\\`
    # continuations); hits are then located by searching the source span.
    end_line: int | None = None


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    term: Term
    kind: str
    line_text: str

    def render(self) -> str:
        return (f"{self.path}:{self.line}: banned term {self.term.text!r} in {self.kind} "
                f"(use: {self.term.use}): {self.line_text.strip()}")


@dataclass(frozen=True)
class AllowEntry:
    path: str
    term: str
    reason: str
    line_contains: str | None = None

    def covers(self, hit: Hit) -> bool:
        if not fnmatch.fnmatch(hit.path, self.path):
            return False
        if self.term.casefold() != hit.term.text.casefold():
            return False
        return self.line_contains is None or self.line_contains in hit.line_text


# --- term list -------------------------------------------------------------------------

def _normalise_term(raw: str) -> str:
    """'"Thinking…"' -> 'Thinking'; quotes and trailing ellipses are table decoration."""
    term = raw.strip().strip("\"'“”").strip()
    term = re.sub(r"(…|\.\.\.)$", "", term).strip()
    return term.replace("’", "'")


def _compile(term: str, case_sensitive: bool) -> re.Pattern[str]:
    words = [re.escape(w).replace("'", "['’]") for w in term.split()]
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(r"(?<![\w'’])" + r"\s+".join(words) + r"(?![\w'’])", flags)


def make_term(text: str, use: str = "", case_sensitive: bool = False) -> Term:
    text = _normalise_term(text)
    return Term(text, use, _compile(text, case_sensitive))


def terms_from_yaml(data: object) -> list[Term]:
    """Parse {avoid: [..], use: {term: text}, case_sensitive: [..]} as in docs/language.md."""
    if not isinstance(data, dict) or not isinstance(data.get("avoid"), list):
        raise ValueError("term list must be a mapping with an `avoid` list")
    use = data.get("use") or {}
    exact = {_normalise_term(str(t)) for t in data.get("case_sensitive") or []}
    terms = []
    for raw in data["avoid"]:
        text = _normalise_term(str(raw))
        terms.append(make_term(text, str(use.get(raw, use.get(text, ""))), text in exact))
    return terms


def terms_from_markdown(markdown: str) -> list[Term]:
    """Terms from the first ```yaml fenced block that has an `avoid` key; [] when none."""
    blocks = re.findall(r"^```ya?ml[^\n]*\n(.*?)^```", markdown, re.MULTILINE | re.DOTALL)
    for block in blocks:
        data = yaml.safe_load(block)
        if isinstance(data, dict) and "avoid" in data:
            return terms_from_yaml(data)
    return []


def load_terms(doc: Path = LANGUAGE_DOC) -> tuple[list[Term], str]:
    """Return the term list and where it came from."""
    if doc.exists():
        terms = terms_from_markdown(doc.read_text(encoding="utf-8"))
        if terms:
            return terms, str(doc)
    return terms_from_yaml(yaml.safe_load(FALLBACK_YAML)), "spec §14.2 fallback list"


def load_allowlist(path: Path = ALLOWLIST) -> list[AllowEntry]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = []
    for i, raw in enumerate(data.get("entries") or []):
        missing = [k for k in ("path", "term", "reason") if not str(raw.get(k) or "").strip()]
        if missing:
            raise ValueError(f"{path.name} entry {i}: missing {', '.join(missing)}")
        entries.append(AllowEntry(raw["path"], _normalise_term(raw["term"]), raw["reason"],
                                  raw.get("line_contains")))
    return entries


# --- .tsx text extraction --------------------------------------------------------------

_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")
_JSX_PRECEDERS = set("(,=:[!&|?{};>")
_JSX_PRECEDING_WORDS = {"return", "default", "yield", "case", "in", "of", "else", "do"}
_IMPORT_WORDS = {"import", "from", "require"}


class TsxScanner:
    """Small TSX lexer that yields user-visible text. Not a full parser: it tells JSX from
    generics/comparisons by the token before `<`, and regex from division the same way."""

    def __init__(self, source: str):
        self.src = source
        self.n = len(source)
        self.i = 0
        self.out: list[Text] = []
        self.last_word = ""
        self.last_char = ""

    def line_at(self, pos: int) -> int:
        return self.src.count("\n", 0, pos) + 1

    def scan(self) -> list[Text]:
        self.code(stop_on_brace=False)
        return self.out

    def emit(self, value: str, pos: int, kind: str) -> None:
        if value.strip():
            self.out.append(Text(value, self.line_at(pos), kind))

    # -- code -----------------------------------------------------------------------------

    def code(self, stop_on_brace: bool) -> None:
        depth = 0
        while self.i < self.n:
            c = self.src[self.i]
            nxt = self.src[self.i + 1] if self.i + 1 < self.n else ""
            if c.isspace():
                self.i += 1
                continue
            if c == "/" and nxt == "/":
                end = self.src.find("\n", self.i)
                self.i = self.n if end == -1 else end
                continue
            if c == "/" and nxt == "*":
                end = self.src.find("*/", self.i + 2)
                self.i = self.n if end == -1 else end + 2
                continue
            if c in "\"'":
                start = self.i
                value = self.string(c)
                self.string_literal(value, start)
                self.mark(c)
                continue
            if c == "`":
                self.template()
                self.mark("`")
                continue
            if c == "/" and self.regex_allowed():
                self.regex()
                self.mark("/")
                continue
            if c == "<" and self.jsx_allowed() and (nxt.isalpha() or nxt == ">"):
                self.jsx_element()
                self.mark(">")
                continue
            if c.isalpha() or c in "_$":
                start = self.i
                while self.i < self.n and (self.src[self.i].isalnum() or self.src[self.i] in "_$"):
                    self.i += 1
                self.last_word = self.src[start:self.i]
                self.last_char = "w"
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0 and stop_on_brace:
                    self.i += 1
                    return
                depth -= 1
            self.i += 1
            self.mark(c)

    def mark(self, char: str) -> None:
        # last_word survives "(" so `require("x")` and `import("x")` still read as imports.
        self.last_char = char
        if char != "(":
            self.last_word = ""

    def regex_allowed(self) -> bool:
        if self.last_char == "w":
            return self.last_word in _JSX_PRECEDING_WORDS or self.last_word == "typeof"
        return self.last_char == "" or self.last_char in _REGEX_PRECEDERS

    def jsx_allowed(self) -> bool:
        if self.last_char == "w":
            return self.last_word in _JSX_PRECEDING_WORDS
        if self.last_char == ">":
            # `=>` (arrow body) or the end of a previous JSX element; `a > <b>` is not TSX.
            return True
        return self.last_char == "" or self.last_char in _JSX_PRECEDERS

    def string_literal(self, value: str, start: int) -> None:
        # `import x from "y"`, `require("y")`, `import("y")`.
        if self.last_word in _IMPORT_WORDS:
            return
        if MACHINE_KEY.match(value):
            return
        self.emit(value, start, "string literal")

    def string(self, quote: str) -> str:
        self.i += 1
        parts = []
        while self.i < self.n:
            c = self.src[self.i]
            if c == "\\" and self.i + 1 < self.n:
                parts.append(self.src[self.i + 1])
                self.i += 2
                continue
            self.i += 1
            if c == quote or c == "\n":
                break
            parts.append(c)
        return "".join(parts)

    def template(self) -> None:
        self.i += 1
        start, buf = self.i, []
        while self.i < self.n:
            c = self.src[self.i]
            if c == "\\" and self.i + 1 < self.n:
                buf.append(self.src[self.i + 1])
                self.i += 2
                continue
            if c == "`":
                self.i += 1
                break
            if c == "$" and self.src.startswith("${", self.i):
                self.flush_template(buf, start)
                self.i += 2
                self.last_char, self.last_word = "{", ""
                self.code(stop_on_brace=True)
                start, buf = self.i, []
                continue
            buf.append(c)
            self.i += 1
        self.flush_template(buf, start)

    def flush_template(self, buf: list[str], start: int) -> None:
        value = "".join(buf)
        if not MACHINE_KEY.match(value.strip()):
            self.emit(value, start, "template literal")
        buf.clear()

    def regex(self) -> None:
        self.i += 1
        in_class = False
        while self.i < self.n:
            c = self.src[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "\n":
                return
            self.i += 1
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
        while self.i < self.n and self.src[self.i].isalpha():
            self.i += 1

    # -- JSX ------------------------------------------------------------------------------

    def jsx_element(self) -> None:
        """Consume `<Tag ...>children</Tag>`, `<Tag ... />` or a fragment."""
        self.i += 1
        while self.i < self.n and (self.src[self.i].isalnum() or self.src[self.i] in "_$.:-"):
            self.i += 1
        if self.jsx_attributes():
            return
        self.jsx_children()

    def jsx_attributes(self) -> bool:
        """Consume attributes up to the tag end; True when the tag self-closed."""
        while self.i < self.n:
            c = self.src[self.i]
            if c.isspace():
                self.i += 1
            elif self.src.startswith("/>", self.i):
                self.i += 2
                return True
            elif c == ">":
                self.i += 1
                return False
            elif c == "{":
                self.i += 1
                self.last_char, self.last_word = "{", ""
                self.code(stop_on_brace=True)
            elif c == "<":
                # Generic on a component (`<Select<Option> ...>`); skip to its `>`.
                end = self.src.find(">", self.i)
                self.i = self.n if end == -1 else end + 1
            else:
                start = self.i
                while self.i < self.n and not self.src[self.i].isspace() \
                        and self.src[self.i] not in "=/>{":
                    self.i += 1
                name = self.src[start:self.i]
                if self.i < self.n and self.src[self.i] == "=":
                    self.i += 1
                    self.jsx_attribute_value(name)
        return False

    def jsx_attribute_value(self, name: str) -> None:
        if self.i >= self.n:
            return
        c = self.src[self.i]
        if c in "\"'":
            start = self.i
            value = self.string(c)
            copy_attr = name not in NON_COPY_ATTRS and not name.startswith("data-")
            if copy_attr and not MACHINE_KEY.match(value):
                self.emit(value, start, f"JSX attribute {name}")
        elif c == "{":
            self.i += 1
            self.last_char, self.last_word = "{", ""
            self.code(stop_on_brace=True)

    def jsx_children(self) -> None:
        start, buf = self.i, []
        while self.i < self.n:
            c = self.src[self.i]
            if c == "{":
                self.emit_jsx_text(buf, start)
                self.i += 1
                self.last_char, self.last_word = "{", ""
                self.code(stop_on_brace=True)
                start, buf = self.i, []
                continue
            if c == "<":
                self.emit_jsx_text(buf, start)
                if self.src.startswith("</", self.i):
                    end = self.src.find(">", self.i)
                    self.i = self.n if end == -1 else end + 1
                    return
                self.jsx_element()
                start, buf = self.i, []
                continue
            buf.append(c)
            self.i += 1
        self.emit_jsx_text(buf, start)

    def emit_jsx_text(self, buf: list[str], start: int) -> None:
        self.emit(html.unescape("".join(buf)), start, "JSX text")


def tsx_texts(source: str) -> list[Text]:
    return TsxScanner(source).scan()


# --- prompts embedded in Python -------------------------------------------------------

PROMPT_NAME = re.compile(r"(PROMPTS?|ADDENDUM|INSTRUCTIONS?)$")
_LLM_CALL_METHODS = {"create", "stream"}


def _target_names(node: ast.AST) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _is_messages_call(call: ast.Call) -> bool:
    """`<anything>.messages.create(...)` / `.messages.stream(...)`."""
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr in _LLM_CALL_METHODS
            and isinstance(func.value, ast.Attribute) and func.value.attr == "messages")


class PythonPromptScanner:
    """Collects prompt text from a Python module: every string in the value of an
    assignment to a name ending in PROMPT(S)/ADDENDUM/INSTRUCTION(S), and every string that
    reaches `system=` of a `.messages.create` / `.messages.stream` call. Both follow names
    assigned in the same module (not imports). Machine-key strings (paths, dict keys) are skipped."""

    def __init__(self, source: str):
        self.src = source
        self.tree = ast.parse(source)
        self.parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent
        self.seen: set[int] = set()
        self.out: list[Text] = []

    def scan(self) -> list[Text]:
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value \
                    and any(PROMPT_NAME.search(n) for n in _target_names(node)):
                self.collect(node.value, scope=self.scope_of(node), followed=set())
            elif isinstance(node, ast.Call) and _is_messages_call(node):
                for kw in node.keywords:
                    if kw.arg == "system":
                        self.collect(kw.value, scope=self.scope_of(node), followed=set())
        return self.out

    def scope_of(self, node: ast.AST) -> ast.AST:
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return self.tree

    def assignments(self, name: str, scope: ast.AST) -> Iterator[ast.expr]:
        """RHS of every assignment to `name` in scope, then at module level."""
        for where in dict.fromkeys((scope, self.tree)):
            for node in ast.walk(where):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) \
                        and node.value is not None and name in _target_names(node) \
                        and (where is scope or self.scope_of(node) is self.tree):
                    yield node.value

    def collect(self, expr: ast.expr, scope: ast.AST | None = None,
                followed: set[str] | None = None) -> None:
        for node in ast.walk(expr):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if not isinstance(self.parents.get(node), ast.JoinedStr):
                    self.emit(node, node.value)
            elif isinstance(node, ast.JoinedStr):
                parts = [v.value if isinstance(v, ast.Constant) else " " for v in node.values]
                self.emit(node, "".join(parts))
            elif isinstance(node, ast.Name) and followed is not None \
                    and node.id not in followed:
                followed.add(node.id)
                for value in self.assignments(node.id, scope or self.tree):
                    self.collect(value, scope, followed)

    def emit(self, node: ast.expr, value: str) -> None:
        if id(node) in self.seen or not value.strip() or MACHINE_KEY.match(value.strip()):
            return
        self.seen.add(id(node))
        self.out.append(Text(value, node.lineno, "engine prompt",
                             end_line=getattr(node, "end_lineno", node.lineno)))


def python_prompt_texts(source: str) -> list[Text]:
    return PythonPromptScanner(source).scan()


# --- scanning --------------------------------------------------------------------------

def _source_lines_with(term: Term, text: Text, lines: list[str]) -> list[int]:
    assert text.end_line is not None
    return [n for n in range(text.line, text.end_line + 1)
            for _ in term.pattern.finditer(lines[n - 1])]


def _hits_in(path: str, texts: Iterable[Text], lines: list[str], terms: list[Term]) -> list[Hit]:
    hits = []
    for text in texts:
        for term in terms:
            found = None if text.end_line is None else _source_lines_with(term, text, lines)
            for k, match in enumerate(term.pattern.finditer(text.value)):
                if found is None:
                    line = text.line + text.value.count("\n", 0, match.start())
                else:
                    line = found[k] if k < len(found) else text.line
                line_text = lines[line - 1] if 0 < line <= len(lines) else text.value
                hits.append(Hit(path, line, term, text.kind, line_text))
    return hits


def lint_prompt(path: str, source: str, terms: list[Term]) -> list[Hit]:
    return _hits_in(path, [Text(source, 1, "system prompt")], source.splitlines(), terms)


def lint_tsx(path: str, source: str, terms: list[Term]) -> list[Hit]:
    return _hits_in(path, tsx_texts(source), source.splitlines(), terms)


def lint_python(path: str, source: str, terms: list[Term]) -> list[Hit]:
    return _hits_in(path, python_prompt_texts(source), source.splitlines(), terms)


def _walk(root: Path, pattern: str) -> Iterator[Path]:
    """Files under root matching pattern, never descending into SKIP_DIRS."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if fnmatch.fnmatch(name, pattern):
                yield Path(dirpath) / name


def lint_tree(root: Path, terms: list[Term]) -> list[Hit]:
    hits: list[Hit] = []
    for path in _walk(root / "src", "system_prompt.md"):
        rel = path.relative_to(root).as_posix()
        hits.extend(lint_prompt(rel, path.read_text(encoding="utf-8"), terms))
    for code_root in PROMPT_CODE_ROOTS:
        for path in _walk(root / code_root, "*.py"):
            rel = path.relative_to(root).as_posix()
            hits.extend(lint_python(rel, path.read_text(encoding="utf-8"), terms))
    for ui in UI_ROOTS:
        for path in _walk(root / ui, "*.tsx"):
            if path.name.endswith(TEST_SUFFIXES):
                continue
            rel = path.relative_to(root).as_posix()
            hits.extend(lint_tsx(rel, path.read_text(encoding="utf-8"), terms))
    return hits


def apply_allowlist(hits: list[Hit], allow: list[AllowEntry]) -> tuple[list[Hit], list[AllowEntry]]:
    """Return (hits not allowlisted, allowlist entries that matched nothing)."""
    used: set[int] = set()
    remaining = []
    for hit in hits:
        idx = next((i for i, e in enumerate(allow) if e.covers(hit)), None)
        if idx is None:
            remaining.append(hit)
        else:
            used.add(idx)
    return remaining, [e for i, e in enumerate(allow) if i not in used]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    parser.add_argument("--format", choices=("text", "github"), default="text")
    args = parser.parse_args(argv)

    terms, source = load_terms(args.root / "docs" / "language.md")
    hits, unused = apply_allowlist(lint_tree(args.root, terms), load_allowlist(args.allowlist))
    print(f"language-lint: {len(terms)} terms from {source}")
    for entry in unused:
        print(f"warning: allowlist entry matched nothing: {entry.path} / {entry.term!r}")
    for hit in hits:
        if args.format == "github":
            print(f"::error file={hit.path},line={hit.line}::banned term "
                  f"{hit.term.text!r} in {hit.kind} (use: {hit.term.use})")
        print(hit.render())
    print(f"language-lint: {len(hits)} hit(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
