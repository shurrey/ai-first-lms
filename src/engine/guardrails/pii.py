"""PII filter guardrail — detect and redact PII (SPEC-v1 §14.2, spec.md §5.2 step 8).

`scan_and_redact` handles free text. `scan_and_redact_result` handles a parsed tool result:
person-name fields become stable pseudonyms, and every string gets the text scan.
Pseudonyms are salted with PII_PSEUDONYM_SALT; without it a random per-process salt is used,
so pseudonyms change on every restart.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from typing import Any

logger = logging.getLogger(__name__)

REDACTION = "[REDACTED]"
PSEUDONYM_SALT_ENV = "PII_PSEUDONYM_SALT"
PSEUDONYM_HEX_CHARS = 8

# Patterns may define a `pii` group; only that group is redacted (keeps labels like "Passport").
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")),
    # A phone needs a +country code or separators; a bare digit run is coursework, not a phone.
    ("phone", re.compile(
        r"(?<![\w+])\+\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"
        r"|(?<![\w(])(?:1[-.\s])?(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}\b"
    )),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
    ("us_passport", re.compile(
        r"\bpassport(?:\s+(?:no\.?|number|num\.?|#))?\s*[:#]?\s*(?P<pii>[A-Z]\d{8})\b",
        re.IGNORECASE,
    )),
]

# Matches inside a UUID are never PII; an all-digit run of UUID segments can look
# like a card or phone number.
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# Manifest `requires_pii` values that let real person names through.
NAME_ALLOWANCES = frozenset({"display_name", "name"})
PERSON_NAME_KEYS = frozenset({
    "display_name", "student_name", "full_name", "author_name", "learner_name",
    "preferred_name", "first_name", "last_name", "recipient_name", "sender_name",
})
PERSON_ID_KEYS = ("person_id", "student_id", "user_id", "author_id")
# `name` is a person name only in a dict that also carries one of these.
_PERSON_MARKERS = frozenset({*PERSON_ID_KEYS, "email", "roles"})
_STAFF_ROLES = frozenset({"faculty", "advisor", "admin", "program_lead", "instructor", "ta"})


@dataclass
class PIIDetection:
    pii_type: str
    original: str
    start: int
    end: int


@dataclass
class PIIFilterResult:
    text: str
    detections: list[PIIDetection] = field(default_factory=list)
    had_pii: bool = False


def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def scan_and_redact(text: str, allowed_fields: Iterable[str] | None = None) -> PIIFilterResult:
    """Redact PII patterns in `text`; `allowed_fields` names PII types to keep (e.g. "email")."""
    allowed = set(allowed_fields or [])
    detections: list[PIIDetection] = []
    # Spans already taken (UUIDs, earlier detections); overlapping matches are skipped.
    claimed: list[tuple[int, int]] = [(m.start(), m.end()) for m in _UUID.finditer(text)]

    for pii_type, pattern in _PATTERNS:
        if pii_type in allowed:
            continue
        for match in pattern.finditer(text):
            group = "pii" if "pii" in pattern.groupindex else 0
            start, end = match.span(group)
            if any(start < c_end and c_start < end for c_start, c_end in claimed):
                continue
            if pii_type == "credit_card" and not _luhn_ok(match.group()):
                continue
            claimed.append((start, end))
            detections.append(PIIDetection(pii_type, match.group(group), start, end))

    result_text = text
    if detections:
        detections.sort(key=lambda d: d.start, reverse=True)
        for det in detections:
            result_text = result_text[:det.start] + REDACTION + result_text[det.end:]
        detections.sort(key=lambda d: d.start)
        logger.info(
            "PII filter: redacted %d item(s) of types %s",
            len(detections), {d.pii_type for d in detections},
        )
    return PIIFilterResult(text=result_text, detections=detections, had_pii=bool(detections))


@cache
def _process_salt() -> str:
    logger.warning("%s is not set; using a random salt, so pseudonyms are not stable across "
                   "restarts", PSEUDONYM_SALT_ENV)
    return secrets.token_hex(16)


def _pseudonym_salt() -> str:
    return os.environ.get(PSEUDONYM_SALT_ENV) or _process_salt()


def pseudonym(person_key: str) -> str:
    """`Student-XXXXXXXX` for a person id (or, lacking one, the name itself); stable for a
    given salt."""
    digest = hashlib.sha256(f"{_pseudonym_salt()}{person_key}".encode()).hexdigest()
    return f"Student-{digest[:PSEUDONYM_HEX_CHARS].upper()}"


@dataclass(frozen=True)
class ResultRedaction:
    value: Any
    pseudonymized: int  # name fields replaced
    redacted: int  # pattern matches replaced in strings


class _ResultRedactor:
    def __init__(
        self, allowed_fields: Iterable[str], requester_id: str | None, requester_name: str | None
    ) -> None:
        allowed = set(allowed_fields)
        self.keep_names = bool(allowed & NAME_ALLOWANCES)
        self.allowed_types = allowed - NAME_ALLOWANCES
        self.requester_id = requester_id
        self.requester_name = (requester_name or "").strip().casefold()
        self.names: dict[str, str] = {}  # real name -> pseudonym, for free-text substitution
        self.pseudonymized = 0
        self.redacted = 0

    # --- pass 1: decide each person-name field --------------------------------------------

    def collect(self, value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                self.collect(item)
            return
        if not isinstance(value, dict):
            return
        for key in self._name_keys(value):
            name = value[key]
            if isinstance(name, str) and name.strip() and not self._keeps(value, name):
                self.names.setdefault(name, pseudonym(self._person_key(value, name)))
        for item in value.values():
            self.collect(item)

    def _name_keys(self, d: dict[str, Any]) -> list[str]:
        keys = [k for k in d if k in PERSON_NAME_KEYS]
        if "name" in d and _PERSON_MARKERS & d.keys():
            keys.append("name")
        return keys

    def _person_key(self, d: dict[str, Any], name: str) -> str:
        for key in (*PERSON_ID_KEYS, "id"):
            value = d.get(key)
            if isinstance(value, str) and value:
                return value
        return name

    def _keeps(self, d: dict[str, Any], name: str) -> bool:
        if self.keep_names:
            return True
        person = self._person_key(d, name)
        if self.requester_id and person == self.requester_id:
            return True
        if person == name and name.strip().casefold() == self.requester_name:
            return True
        return _is_staff(d)

    # --- pass 2: rewrite ------------------------------------------------------------------

    def rewrite(self, value: Any) -> Any:
        if isinstance(value, dict):
            names = set(self._name_keys(value))
            return {k: (self._name(v) if k in names else self.rewrite(v))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [self.rewrite(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def _name(self, value: Any) -> Any:
        if isinstance(value, str) and value in self.names:
            self.pseudonymized += 1
            return self.names[value]
        return self.rewrite(value)

    def text(self, value: str) -> str:
        result = scan_and_redact(value, allowed_fields=self.allowed_types)
        self.redacted += len(result.detections)
        out = result.text
        for name, alias in self.names.items():
            out, count = re.subn(rf"(?<!\w){re.escape(name)}(?!\w)", alias, out)
            self.pseudonymized += count
        return out


def _is_staff(d: dict[str, Any]) -> bool:
    roles = d.get("roles")
    role_set = {r for r in roles if isinstance(r, str)} if isinstance(roles, list) else set()
    if isinstance(d.get("role"), str):
        role_set.add(d["role"])
    return bool(role_set) and "student" not in role_set and bool(role_set & _STAFF_ROLES)


def scan_and_redact_result(
    value: Any,
    *,
    allowed_fields: Iterable[str] = (),
    requester_id: str | None = None,
    requester_name: str | None = None,
) -> ResultRedaction:
    """Redact a parsed tool result before the model sees it.

    A learner's name field becomes `Student-XXXXXXXX` unless `allowed_fields` (the agent's
    `requires_pii`) includes display_name/name, the person is the requester, or the record is
    staff-only. Replaced names are also replaced wherever they appear in free text.
    """
    redactor = _ResultRedactor(allowed_fields, requester_id, requester_name)
    if isinstance(value, str):
        return ResultRedaction(redactor.text(value), 0, redactor.redacted)
    redactor.collect(value)
    out = redactor.rewrite(value)
    return ResultRedaction(out, redactor.pseudonymized, redactor.redacted)
