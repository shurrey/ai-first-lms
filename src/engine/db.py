from __future__ import annotations

from typing import Any

from engine.models.session import Session
from engine.models.turn import Turn


class SessionStore:
    """In-memory session store. Will be backed by Postgres once T-D-001 lands."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(self, session: Session) -> Session:
        self._sessions[session.id] = session
        return session

    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None


class TurnStore:
    """In-memory turn store. Tracks active and completed turns."""

    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}

    async def create(self, turn: Turn) -> Turn:
        self._turns[turn.id] = turn
        return turn

    async def get(self, turn_id: str) -> Turn | None:
        return self._turns.get(turn_id)

    async def update_status(self, turn_id: str, status: str) -> None:
        if turn_id in self._turns:
            self._turns[turn_id].status = status

    async def add_events(self, turn_id: str, events: list[dict[str, Any]]) -> None:
        if turn_id in self._turns:
            self._turns[turn_id].events.extend(events)

    async def get_events(self, turn_id: str, since_sequence: int = 0) -> list[dict[str, Any]]:
        turn = self._turns.get(turn_id)
        if not turn:
            return []
        return turn.events[since_sequence:]
