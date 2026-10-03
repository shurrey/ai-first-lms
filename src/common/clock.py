"""The LMS's notion of "now" for data windows, honoring LMS_AS_OF.

LMS_AS_OF is an ISO date (`2026-09-15`, meaning 00:00 UTC that day) or an ISO timestamp
(naive means UTC). While set, `now()` returns that fixed instant, so queries against the
seed's absolute dates give the same rows on any day. Unset or blank: the real current time.
Session expiry, audit timestamps and budget clocks use real time, not this.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

AS_OF_ENV = "LMS_AS_OF"


def as_of() -> datetime | None:
    """The fixed instant from LMS_AS_OF, or None when unset. Raises ValueError when malformed."""
    raw = os.environ.get(AS_OF_ENV, "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), datetime.min.time(), UTC)
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{AS_OF_ENV} must be an ISO date or timestamp, got {raw!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def now() -> datetime:
    """Timezone-aware UTC "now": LMS_AS_OF when set, else the real time."""
    fixed = as_of()
    return fixed if fixed is not None else datetime.now(UTC)
