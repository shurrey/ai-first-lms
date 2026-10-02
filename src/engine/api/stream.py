"""GET /api/stream — SSE endpoint for streaming orchestrator events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from engine.auth.deps import CurrentUser
from engine.auth.scope import forbidden, require_own_session
from engine.db import TERMINAL_STATUSES

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/stream")
async def stream(
    request: Request,
    ctx: CurrentUser,
    session_id: str = Query(...),
    turn_id: str = Query(...),
    since_sequence: int = Query(0),
) -> EventSourceResponse:
    """SSE stream of events for an in-progress turn; 403 before streaming if not the caller's."""
    session = await request.app.state.session_store.get(session_id)
    require_own_session(ctx, session, acting=False)
    turn = await request.app.state.turn_store.get(turn_id)
    if turn is not None and turn.session_id != session_id:
        raise forbidden("Not your session.")
    return EventSourceResponse(
        _event_generator(request, session_id, turn_id, since_sequence),
        media_type="text/event-stream",
    )


async def _event_generator(
    request: Request,
    session_id: str,
    turn_id: str,
    since_sequence: int,
) -> AsyncIterator[dict[str, str]]:
    """Replay events after `since_sequence`, then follow the turn until it finishes.

    `sequence` and `timestamp` are the stored per-turn values, so a reconnect sees the
    same numbering as the original stream.
    """
    turn_store = request.app.state.turn_store
    last_seen = since_sequence

    while True:
        if await request.is_disconnected():
            logger.info("SSE client disconnected: session=%s turn=%s", session_id, turn_id)
            return

        turn = await turn_store.get(turn_id)
        if turn is None:
            yield _error_event(session_id, turn_id, last_seen + 1, "Turn not found")
            return

        # Read status before events: everything stored before the turn finished is then
        # drained in this pass, even if the turn finishes while we are yielding.
        finished = turn.status in TERMINAL_STATUSES
        events = await turn_store.get_events(turn_id, since_sequence=last_seen)

        for event_data in events:
            sequence = event_data["sequence"]
            envelope = {
                "event": event_data.get("event", "reasoning"),
                "session_id": session_id,
                "turn_id": turn_id,
                "sequence": sequence,
                "timestamp": event_data["timestamp"],
                "payload": event_data.get("payload", {}),
            }
            yield {
                "event": envelope["event"],
                "data": json.dumps(envelope, default=str),
                "id": str(sequence),
            }
            last_seen = sequence

        if finished:
            logger.info("Turn %s status=%s, closing stream", turn_id, turn.status)
            return

        await asyncio.sleep(0.1)


def _error_event(
    session_id: str, turn_id: str, sequence: int, message: str
) -> dict[str, str]:
    envelope = {
        "event": "error",
        "session_id": session_id,
        "turn_id": turn_id,
        "sequence": sequence,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "payload": {
            "code": "internal",
            "message": message,
            "retriable": False,
        },
    }
    return {
        "event": "error",
        "data": json.dumps(envelope, default=str),
        "id": str(sequence),
    }
