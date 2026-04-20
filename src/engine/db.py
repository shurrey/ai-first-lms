from __future__ import annotations

from engine.models.session import Session


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
