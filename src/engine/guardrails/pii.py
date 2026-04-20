"""PII filter guardrail — detect and redact PII from text (SPEC §14.2)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

REDACTION = "[REDACTED]"

# PII patterns
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
    ("us_passport", re.compile(r"\b[A-Z]\d{8}\b")),
]


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


def scan_and_redact(text: str, allowed_fields: list[str] | None = None) -> PIIFilterResult:
    """Scan text for PII and redact detected patterns.

    Args:
        text: The text to scan.
        allowed_fields: PII types to allow through (e.g., ["email"] if the
            agent manifest declares requires_pii: [email]).
    """
    allowed = set(allowed_fields or [])
    detections: list[PIIDetection] = []
    result_text = text

    for pii_type, pattern in _PATTERNS:
        if pii_type in allowed:
            continue

        for match in pattern.finditer(text):
            detections.append(PIIDetection(
                pii_type=pii_type,
                original=match.group(),
                start=match.start(),
                end=match.end(),
            ))

    if detections:
        # Sort by position descending so replacements don't shift indices
        detections.sort(key=lambda d: d.start, reverse=True)
        for det in detections:
            result_text = result_text[:det.start] + REDACTION + result_text[det.end:]

        # Re-sort ascending for the return value
        detections.sort(key=lambda d: d.start)

        logger.info(
            "PII filter: redacted %d item(s) of types %s",
            len(detections),
            {d.pii_type for d in detections},
        )

    return PIIFilterResult(
        text=result_text,
        detections=detections,
        had_pii=len(detections) > 0,
    )
