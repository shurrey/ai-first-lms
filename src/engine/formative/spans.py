"""Evidence spans must quote the submission verbatim (spec.md §7.3, §20)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A span quotes evidence, not the submission: longer quotes are dropped as `too_long`.
MAX_QUOTE_CHARS = 300


@dataclass(frozen=True)
class SpanCheck:
    kept: list[dict[str, Any]]
    dropped: list[dict[str, Any]]  # each: {quote, reason}


def _offsets_match(body: str, quote: str, start: Any, end: Any) -> bool:
    return (isinstance(start, int) and isinstance(end, int) and not isinstance(start, bool)
            and 0 <= start <= end <= len(body) and body[start:end] == quote)


def check_spans(body: str, spans: Any) -> SpanCheck:
    """Keeps spans whose `quote` occurs exactly in `body` and is at most MAX_QUOTE_CHARS
    long; offsets are corrected to the first occurrence when the given ones do not select
    the quote. Pure."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for span in spans if isinstance(spans, list) else []:
        quote = span.get("quote") if isinstance(span, dict) else None
        if not isinstance(quote, str) or not quote.strip():
            dropped.append({"quote": quote if isinstance(quote, str) else None,
                            "reason": "missing_quote"})
            continue
        if len(quote) > MAX_QUOTE_CHARS:
            dropped.append({"quote": quote[:MAX_QUOTE_CHARS], "reason": "too_long"})
            continue
        if _offsets_match(body, quote, span.get("start"), span.get("end")):
            kept.append({"quote": quote, "start": span["start"], "end": span["end"]})
            continue
        found = body.find(quote)
        if found < 0:
            dropped.append({"quote": quote, "reason": "not_verbatim"})
            continue
        kept.append({"quote": quote, "start": found, "end": found + len(quote)})
    return SpanCheck(kept, dropped)
