"""SSE generator delivers events stored while an earlier event was being yielded."""

from __future__ import annotations

import json
from types import SimpleNamespace

from engine.api.stream import _event_generator


class _Store:
    def __init__(self) -> None:
        self.turn = SimpleNamespace(status="running")
        self.events: list[dict] = [_event(1, "reasoning", {"text": "a"})]

    async def get(self, turn_id: str):
        return self.turn

    async def get_events(self, turn_id: str, since_sequence: int = 0) -> list[dict]:
        return [e for e in self.events if e["sequence"] > since_sequence]


def _event(sequence: int, event: str, payload: dict) -> dict:
    return {"event": event, "payload": payload, "sequence": sequence,
            "timestamp": "2026-10-02T00:00:00.000+00:00"}


class _Request:
    def __init__(self, store: _Store) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(turn_store=store))

    async def is_disconnected(self) -> bool:
        return False


async def test_error_stored_mid_yield_is_still_delivered():
    store = _Store()
    received: list[str] = []
    async for sse in _event_generator(_Request(store), "s1", "t1", 0):
        received.append(json.loads(sse["data"])["event"])
        if len(received) == 1:
            # The turn fails while the consumer holds the first event.
            store.events.append(_event(2, "error", {"code": "internal"}))
            store.turn.status = "error"
    assert received == ["reasoning", "error"]
