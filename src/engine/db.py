"""Session and turn stores: in-process caches that write through to `Persistence`.

Writes go to the cache and then the database; reads hit the cache, then the database.
A database failure is logged at ERROR and never fails the request or the turn. The
cache never evicts, so every turn still running in this process is in it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any

from engine.models.session import Session
from engine.models.turn import Turn
from engine.turn_repository import Persistence

logger = logging.getLogger(__name__)

PERSIST_TIMEOUT_S = 5.0
TERMINAL_STATUSES = ("completed", "error")
INTERRUPTED_MESSAGE = "This response was interrupted when the service restarted. Please ask again."


async def _bounded[T](call: Awaitable[T]) -> T:
    return await asyncio.wait_for(call, timeout=PERSIST_TIMEOUT_S)


class SessionStore:
    def __init__(self, repository: Persistence | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._repository = repository

    def use_repository(self, repository: Persistence | None) -> None:
        self._repository = repository

    async def create(self, session: Session) -> Session:
        self._sessions[session.id] = session
        if self._repository is not None:
            try:
                await _bounded(self._repository.create_session(session))
            except Exception:
                logger.error("Could not persist session %s; it lives only in memory",
                             session.id, exc_info=True)
        return session

    async def get(self, session_id: str) -> Session | None:
        cached = self._sessions.get(session_id)
        if cached is not None or self._repository is None:
            return cached
        try:
            loaded = await _bounded(self._repository.get_session(session_id))
        except Exception:
            logger.error("Could not load session %s from the database", session_id,
                         exc_info=True)
            return None
        if loaded is not None:
            self._sessions.setdefault(session_id, loaded)
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> bool:
        """Removes the cached copy only; the database row is kept for provenance."""
        return self._sessions.pop(session_id, None) is not None


class TurnStore:
    """Events get a per-turn `sequence` (from 1, contiguous) and `timestamp` when added.

    A turn whose database writes fail stops writing for the rest of its life (logged
    once), so `events_log` never holds a turn with gaps followed by later events.
    """

    def __init__(self, repository: Persistence | None = None) -> None:
        self._turns: dict[str, Turn] = {}
        self._repository = repository
        self._unpersisted: set[str] = set()
        self._load_lock = asyncio.Lock()

    def use_repository(self, repository: Persistence | None) -> None:
        self._repository = repository

    async def _persist(self, turn_id: str, what: str, call: Awaitable[None]) -> None:
        try:
            await _bounded(call)
        except Exception:
            self._unpersisted.add(turn_id)
            logger.error("Could not persist %s for turn %s; continuing from memory",
                         what, turn_id, exc_info=True)

    def _writes(self, turn_id: str) -> Persistence | None:
        if self._repository is None or turn_id in self._unpersisted:
            return None
        return self._repository

    async def create(self, turn: Turn) -> Turn:
        self._turns[turn.id] = turn
        repo = self._writes(turn.id)
        if repo is not None:
            await self._persist(turn.id, "turn", repo.create_turn(turn))
        return turn

    async def get(self, turn_id: str) -> Turn | None:
        cached = self._turns.get(turn_id)
        if cached is not None or self._repository is None:
            return cached
        async with self._load_lock:
            if turn_id not in self._turns:
                loaded = await self._load(turn_id)
                if loaded is None:
                    return None
                self._turns[turn_id] = loaded
                if loaded.status not in TERMINAL_STATUSES:
                    await self._close_interrupted(loaded)
        return self._turns[turn_id]

    async def _load(self, turn_id: str) -> Turn | None:
        assert self._repository is not None
        try:
            return await _bounded(self._repository.get_turn(turn_id))
        except Exception:
            logger.error("Could not load turn %s from the database", turn_id, exc_info=True)
            return None

    async def _close_interrupted(self, turn: Turn) -> None:
        # Not cached yet still running in the database: the process that ran it is gone.
        logger.warning("Turn %s was interrupted by a restart (status=%s); closing it",
                       turn.id, turn.status)
        await self.add_events(turn.id, [{
            "event": "error",
            "payload": {"code": "internal", "message": INTERRUPTED_MESSAGE,
                        "retriable": True},
        }])
        await self.update_status(turn.id, "error")

    async def update_status(self, turn_id: str, status: str) -> None:
        turn = self._turns.get(turn_id)
        if turn is None:
            return
        turn.status = status
        repo = self._writes(turn_id)
        if repo is not None:
            await self._persist(turn_id, f"status {status}",
                                repo.update_turn_status(turn_id, status))

    async def record_usage(self, turn_id: str, cost_usd: float, tokens: int) -> None:
        repo = self._writes(turn_id)
        if turn_id in self._turns and repo is not None:
            await self._persist(turn_id, "usage",
                                repo.record_turn_usage(turn_id, cost_usd, tokens))

    async def add_events(self, turn_id: str, events: list[dict[str, Any]]) -> None:
        turn = self._turns.get(turn_id)
        if turn is None or not events:
            return
        stamped: list[dict[str, Any]] = []
        # Sequence is assigned with no await in between, so concurrent sinks never collide.
        for event in events:
            stamped.append({
                **event,
                "sequence": len(turn.events) + 1,
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            })
            turn.events.append(stamped[-1])
        repo = self._writes(turn_id)
        if repo is not None:
            await self._persist(turn_id, "events",
                                repo.append_events(turn.session_id, turn_id, stamped))

    async def get_events(self, turn_id: str, since_sequence: int = 0) -> list[dict[str, Any]]:
        """Events with `sequence` greater than `since_sequence`, in order."""
        turn = await self.get(turn_id)
        if turn is None:
            return []
        return [e for e in turn.events if e["sequence"] > since_sequence]

    async def get_conversation_history(self, session_id: str) -> list[dict[str, str]]:
        """Build conversation history from completed turns in this session."""
        history: list[dict[str, str]] = []
        for turn in self._turns.values():
            if turn.session_id != session_id or turn.status != "completed":
                continue
            # Add user message (skip brief synthetic messages)
            if turn.message and turn.message != "__brief__":
                history.append({"role": "user", "content": turn.message})
            # Find the final event's answer_markdown for the assistant response
            for event in reversed(turn.events):
                if event.get("event") == "final":
                    answer = event.get("payload", {}).get("answer_markdown", "")
                    if answer:
                        history.append({"role": "assistant", "content": answer})
                    break
        return history
