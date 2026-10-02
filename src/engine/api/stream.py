"""GET /api/stream — SSE endpoint for streaming orchestrator events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/stream")
async def stream(
    request: Request,
    session_id: str = Query(...),
    turn_id: str = Query(...),
    since_sequence: int = Query(0),
) -> EventSourceResponse:
    """SSE stream of events for an in-progress turn."""
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
    """Poll turn store for events and yield them as SSE data."""
    turn_store = request.app.state.turn_store
    last_seen = since_sequence
    sequence_counter = max(since_sequence, 1)

    while True:
        # Check if client disconnected
        if await request.is_disconnected():
            logger.info("SSE client disconnected: session=%s turn=%s", session_id, turn_id)
            return

        turn = await turn_store.get(turn_id)
        if turn is None:
            yield _error_event(session_id, turn_id, sequence_counter, "Turn not found")
            return

        # Read status before events: everything stored before the turn finished is then
        # drained in this pass, even if the turn finishes while we are yielding.
        finished = turn.status in ("completed", "error")
        events = await turn_store.get_events(turn_id, since_sequence=last_seen)

        for event_data in events:
            envelope = {
                "event": event_data.get("event", "reasoning"),
                "session_id": session_id,
                "turn_id": turn_id,
                "sequence": sequence_counter,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "payload": event_data.get("payload", {}),
            }
            yield {
                "event": envelope["event"],
                "data": json.dumps(envelope, default=str),
                "id": str(sequence_counter),
            }
            sequence_counter += 1
            last_seen += 1

        if finished:
            logger.info("Turn %s status=%s, closing stream", turn_id, turn.status)
            return

        # Poll interval
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
