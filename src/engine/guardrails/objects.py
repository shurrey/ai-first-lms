"""Object-level scope helpers for id-keyed tools: the draft ledger and identity-key paths.

No MCP tool reads a grade or a message draft back by id, so the gateway remembers the drafts
it executed (`DraftLedger`). The ledger lives in this process: after a restart a draft must be
made again before it can be committed or sent.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

DraftKind = Literal["grade", "message"]

# Tool that creates a draft -> (ledger kind, id key in its result).
DRAFTING_TOOLS: dict[str, tuple[DraftKind, str]] = {
    "assessments.draft_grade": ("grade", "grade_id"),
    "communications.draft_message": ("message", "draft_id"),
}

# Keys naming the object or person a call acts on; an approver's edit may not change them.
IDENTITY_KEYS = frozenset({
    "grade_id", "draft_id", "pending_id", "submission_id", "person_id", "student_id",
    "course_id", "session_id", "bank_id", "person_ids", "student_ids",
    "content_id", "attestation_id", "aligned_nodes",
})


@dataclass(frozen=True)
class DraftRecord:
    kind: DraftKind
    object_id: str
    author_id: str  # the requester whose call created it
    args: dict[str, Any] = field(default_factory=dict)  # as executed


class DraftLedger:
    """Drafts created through the gateway, by id; oldest entries drop past `capacity`.

    Must be used from a single event loop.
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self._capacity = capacity
        self._records: OrderedDict[tuple[DraftKind, str], DraftRecord] = OrderedDict()

    def remember(
        self, kind: DraftKind, object_id: str, author_id: str, args: dict[str, Any]
    ) -> None:
        self._records[(kind, object_id)] = DraftRecord(kind, object_id, author_id, dict(args))
        self._records.move_to_end((kind, object_id))
        while len(self._records) > self._capacity:
            self._records.popitem(last=False)

    def get(self, kind: DraftKind, object_id: Any) -> DraftRecord | None:
        if not isinstance(object_id, str):
            return None
        return self._records.get((kind, object_id))

    def record_result(self, tool: str, author_id: str, args: dict[str, Any], raw: str) -> None:
        """Remember the draft a successful drafting call returned; other calls are ignored."""
        entry = DRAFTING_TOOLS.get(tool)
        if entry is None:
            return
        kind, id_key = entry
        parsed = parse_object(raw)
        object_id = parsed.get(id_key) if parsed else None
        if isinstance(object_id, str) and object_id:
            self.remember(kind, object_id, author_id, args)


def parse_object(raw: Any) -> dict[str, Any] | None:
    """A JSON object from a tool result (text or already parsed), else None."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def identity_paths(value: Any, path: tuple[Any, ...] = ()) -> dict[tuple[Any, ...], Any]:
    """Every IDENTITY_KEYS entry at any depth, keyed by its path."""
    found: dict[tuple[Any, ...], Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in IDENTITY_KEYS:
                found[(*path, key)] = item
            else:
                found.update(identity_paths(item, (*path, key)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.update(identity_paths(item, (*path, i)))
    return found
