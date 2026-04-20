"""SSE streaming helper — wraps an async event source into a StreamingResponse."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator

from sse_starlette.sse import EventSourceResponse

from engine.streaming.events import EventEnvelope

logger = logging.getLogger(__name__)


async def _event_generator(
    event_source: AsyncIterator[EventEnvelope],
) -> AsyncIterator[dict[str, str]]:
    """Convert EventEnvelope objects into SSE data dicts for sse-starlette."""
    try:
        async for envelope in event_source:
            yield {
                "event": envelope.event,
                "data": json.dumps(envelope.model_dump(), default=str),
            }
    except asyncio.CancelledError:
        logger.info("SSE client disconnected, cleaning up generator")
        return
    except Exception:
        logger.exception("Error in SSE event generator")
        raise
    finally:
        # Ensure the source generator is closed on disconnect or completion
        if isinstance(event_source, AsyncGenerator):
            await event_source.aclose()


def stream_events(event_source: AsyncIterator[EventEnvelope]) -> EventSourceResponse:
    """Create an SSE StreamingResponse from an async iterator of EventEnvelopes.

    Handles client disconnect by cancelling the underlying generator.
    """
    return EventSourceResponse(
        _event_generator(event_source),
        media_type="text/event-stream",
    )
