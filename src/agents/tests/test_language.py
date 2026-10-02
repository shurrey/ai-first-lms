"""Agent prompts describe the agents as software tools (spec.md §14, docs/language.md)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.agents.eval_harness import AGENTS_DIR

REPO_ROOT = AGENTS_DIR.parents[1]
LANGUAGE_GUIDE = REPO_ROOT / "docs" / "language.md"
PROMPTS = sorted(AGENTS_DIR.glob("*/system_prompt.md"))
CHECKED_DOCS = PROMPTS + [REPO_ROOT / "docs" / "agents.md"]

# Quoted speech from a person in an exemplar, not the agent describing itself.
ALLOWLISTED_LINE_PREFIXES = (
    "**Student:**",
    "**Faculty:**",
    "**Advisor:**",
    "**Admin:**",
    "**Instructional designer:**",
)


def _term_list() -> dict:
    text = LANGUAGE_GUIDE.read_text()
    block = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert block, "docs/language.md has no ```yaml term block"
    return yaml.safe_load(block.group(1))


def _patterns(terms: dict) -> list[tuple[str, re.Pattern]]:
    case_sensitive = set(terms.get("case_sensitive", []))
    return [
        (
            term,
            re.compile(
                rf"(?<![\w']){re.escape(term)}(?![\w'])",
                0 if term in case_sensitive else re.IGNORECASE,
            ),
        )
        for term in terms["avoid"]
    ]


def find_avoided_terms(text: str, terms: dict) -> list[tuple[int, str]]:
    """(line number, term) for every avoided term outside an allowlisted line."""
    patterns = _patterns(terms)
    hits = []
    for number, line in enumerate(text.replace("’", "'").splitlines(), start=1):
        if line.lstrip().startswith(ALLOWLISTED_LINE_PREFIXES):
            continue
        hits.extend((number, term) for term, pattern in patterns if pattern.search(line))
    return hits


def test_term_list_has_avoid_and_use_for_every_term():
    terms = _term_list()
    assert terms["avoid"]
    assert set(terms["avoid"]) <= set(terms["use"])
    assert set(terms.get("case_sensitive", [])) <= set(terms["avoid"])


@pytest.mark.parametrize("path", CHECKED_DOCS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_avoided_terms(path: Path):
    assert find_avoided_terms(path.read_text(), _term_list()) == []


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.parent.name)
def test_prompt_introduces_agent_as_software_tool(path: Path):
    line_3 = path.read_text().splitlines()[2]
    assert re.match(r"You are the [A-Z][\w ]+, a [\w-]*\s?software tool in an AI-native learning platform", line_3)


def test_tutor_prompt_line_3_matches_spec():
    line_3 = (AGENTS_DIR / "tutor" / "system_prompt.md").read_text().splitlines()[2]
    assert line_3.startswith("You are the Tutor, a software tool in an AI-native learning platform")


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.parent.name)
def test_prompt_tells_agent_to_label_output_generated_and_cite(path: Path):
    text = path.read_text()
    section = text.split("## Describing your output", 1)
    assert len(section) == 2
    body = section[1].split("\n## ", 1)[0].lower()
    assert "generated" in body
    assert "evidence" in body or "cite" in body


@pytest.mark.parametrize(
    "text, expected",
    [
        ("You are a learning companion.", ["companion"]),
        ("The Tutor knows the answer.", ["knows"]),
        ("I’m happy to help.", ["I'm happy to"]),
        ("Thinking...", ["Thinking"]),
        ("Speaker: AI Tutor", ["AI Tutor"]),
        ("recursive thinking and friendly hints", []),
        ("Bloom level: remember | understand | apply", []),
        ('**Student:** "I think my friend knows this."', []),
    ],
)
def test_find_avoided_terms(text: str, expected: list[str]):
    assert [term for _, term in find_avoided_terms(text, _term_list())] == expected
