"""GET /api/access-log: the admin view of data_access_log (spec.md §12.3).

Reading the log is not itself logged: it holds who read what, never learner content.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from engine.auth.access_log import AccessFilter, AccessLog, AccessRow
from engine.auth.capabilities import has_capability
from engine.auth.deps import CurrentUser
from engine.auth.scope import forbidden

router = APIRouter()

CAPABILITY = "access_log"
DEFAULT_LIMIT, MAX_LIMIT = 50, 200

Resource = Literal["transcript", "profile", "analyst_summary", "submission"]


def _access_log(request: Request) -> AccessLog:
    log = getattr(request.app.state, "access_log", None)
    if log is None:
        raise HTTPException(status_code=503, detail="The access log is unavailable.")
    return log  # type: ignore[no-any-return]


def encode_cursor(row: AccessRow) -> str:
    return base64.urlsafe_b64encode(f"{row.created_at.isoformat()}|{row.id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Raises HTTPException 422 for anything `encode_cursor` did not produce."""
    try:
        stamp, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().rsplit("|", 1)
        decoded = datetime.fromisoformat(stamp), int(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid before cursor.") from None
    if decoded[0].tzinfo is None:
        raise HTTPException(status_code=422, detail="Invalid before cursor.")
    return decoded


def _entry(row: AccessRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "actor": {"id": row.actor_id, "display_name": row.actor_name},
        "subject_id": row.subject_id,
        "resource": row.resource,
        "resource_id": row.resource_id,
        "purpose": row.purpose,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/api/access-log")
async def list_access_log(
    request: Request,
    ctx: CurrentUser,
    subject_id: uuid.UUID,
    resource: Resource | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Newest first. `from` is inclusive and `to` exclusive; `before` is the previous page's
    `next_before`. Admin only."""
    if not has_capability(ctx.active_role, CAPABILITY):
        raise forbidden()
    where = AccessFilter(resource=resource, start=start, end=end,
                         before=decode_cursor(before) if before else None)
    rows = await _access_log(request).list_by_subject(str(subject_id), limit=limit + 1,
                                                      where=where)
    page = rows[:limit]
    more = len(rows) > limit
    return {"entries": [_entry(r) for r in page],
            "next_before": encode_cursor(page[-1]) if more and page else None}
