"""Argument parsing and coded errors shared by the formative-loop tools.

Parsers raise ValueError with a message naming the argument; handlers turn it into
`validation_error`. Other failures carry `code`: not_found, conflict or forbidden.
"""
from __future__ import annotations

import uuid
from typing import Any

MAX_TEXT_CHARS = 4_000


def tool_error(message: str, code: str) -> dict[str, Any]:
    return {"error": message, "code": code}


def not_found(message: str) -> dict[str, Any]:
    return tool_error(message, "not_found")


def conflict(message: str) -> dict[str, Any]:
    return tool_error(message, "conflict")


def forbidden(message: str) -> dict[str, Any]:
    return tool_error(message, "forbidden")


def uuid_arg(args: dict[str, Any], key: str, *, required: bool) -> uuid.UUID | None:
    """Raises ValueError (message names the argument) on a missing or malformed id."""
    value = args.get(key)
    if value in (None, ""):
        if required:
            raise ValueError(f"{key} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a UUID string")
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValueError(f"{key} must be a UUID") from None


def uuid_list(value: Any, key: str, *, max_items: int) -> list[uuid.UUID]:
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"{key} must be a list of at most {max_items} UUIDs")
    out: list[uuid.UUID] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} must contain UUID strings")
        try:
            parsed = uuid.UUID(item)
        except ValueError:
            raise ValueError(f"{key} must contain UUIDs") from None
        if parsed in out:
            raise ValueError(f"{key} lists {item} twice")
        out.append(parsed)
    return out


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def text_arg(value: Any, key: str, *, max_chars: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    if len(value) > max_chars:
        raise ValueError(f"{key} must be at most {max_chars} characters")
    return value
