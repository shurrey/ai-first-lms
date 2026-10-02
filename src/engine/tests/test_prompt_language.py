"""Engine-embedded prompts describe a software tool, not a warm persona (spec.md §14.2)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from engine.agents.runner import _TOOL_USE_ADDENDUM
from engine.brief import _COACHING_PROMPTS, COACHING_SYSTEM_PROMPT, FALLBACK_COACHING_MESSAGE

ENGINE = Path(__file__).resolve().parents[1]
PROMPT_MODULES = ("brief.py", "lifecycle.py", "podcast.py", "analyst.py", "graph/interpret.py",
                  "agents/runner.py", "api/podcast.py")
PERSONA_PHRASES = (r"\bwarm(ly)?\b", r"I'm here to help", r"Great to see you",
                   r"\bI'm going to\b", r"\bI've (also )?created\b", r"\bI'd love to\b",
                   r"\bI'm (so )?(glad|excited|thrilled)\b", r"\bAI assistant\b",
                   r"\bYou are creating\b")


def _strings(path: Path) -> list[tuple[int, str]]:
    """String constants in a module (f-string parts included); comments are not strings."""
    tree = ast.parse(path.read_text())
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


@pytest.mark.parametrize("module", PROMPT_MODULES)
def test_prompt_strings_have_no_warm_persona_phrasing(module):
    hits = [(line, phrase) for line, text in _strings(ENGINE / module)
            for phrase in PERSONA_PHRASES if re.search(phrase, text, re.IGNORECASE)]
    assert hits == []


def test_tutor_coaching_prompt_presents_a_software_tool():
    assert "a software tool" in COACHING_SYSTEM_PROMPT
    assert all("assistant tool" in p for k, p in _COACHING_PROMPTS.items() if k != "student")
    assert "I'm" not in FALLBACK_COACHING_MESSAGE


def test_agent_addendum_asks_for_generated_outputs_with_sources():
    assert "You are a software tool" in _TOOL_USE_ADDENDUM
    assert "as generated" in _TOOL_USE_ADDENDUM and "sources" in _TOOL_USE_ADDENDUM


def _module_constant(path: Path, name: str) -> str:
    # Read via the AST: importing engine.podcast creates /app/audio.
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def test_podcast_prompt_describes_speakers_by_role_not_as_people():
    prompt = _module_constant(ENGINE / "podcast.py", "PODCAST_SCRIPT_PROMPT")
    for phrase in (r"\bgenuine(ly)?\b", r"\breal conversation\b", r"\bwants to understand\b",
                   r"\benthusiastic\b"):
        assert not re.search(phrase, prompt, re.IGNORECASE), phrase
    assert "HOST:" in prompt and "EXPERT:" in prompt
