"""Prompt-injection defense utilities for sub-agents."""

from __future__ import annotations


def wrap_user_content(text: str) -> str:
    """Wrap retrieved content in <user_content> delimiters.

    Every text field retrieved from the DB or MCP tools must be wrapped
    before being injected into an LLM prompt.  The system prompt instructs
    the model to treat wrapped content as data, not instructions.
    """
    return f"<user_content>{text}</user_content>"


def wrap_fields(record: dict, fields: list[str]) -> dict:
    """Return a copy of *record* with the named string fields wrapped."""
    out = dict(record)
    for field in fields:
        value = out.get(field)
        if isinstance(value, str):
            out[field] = wrap_user_content(value)
    return out
