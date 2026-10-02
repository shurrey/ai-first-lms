"""In-memory `Persistence` for engine tests that must run without a database."""

from __future__ import annotations

import copy
from typing import Any

from engine.models.session import Session
from engine.models.turn import Turn
from engine.turn_repository import ToolCallRow


class FakePersistence:
    """Rows survive across app instances when the same object is shared, like a database.

    `fail = True` makes every call raise, as an unreachable database would.
    """

    def __init__(self) -> None:
        self.fail = False
        self.sessions: dict[str, Session] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.tool_calls: list[ToolCallRow] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("database is down")

    async def record_tool_call(self, row: ToolCallRow) -> bool:
        self._check()
        if row.turn_id not in self.turns:
            return False
        self.tool_calls.append(row)
        return True

    async def create_session(self, session: Session) -> None:
        self._check()
        self.sessions.setdefault(session.id, session.model_copy(deep=True))

    async def get_session(self, session_id: str) -> Session | None:
        self._check()
        stored = self.sessions.get(session_id)
        return stored.model_copy(deep=True) if stored else None

    async def create_turn(self, turn: Turn) -> None:
        self._check()
        if turn.id in self.turns:
            raise ValueError(f"duplicate turn {turn.id}")
        self.turns[turn.id] = {"session_id": turn.session_id, "message": turn.message,
                               "status": turn.status, "created_at": turn.created_at,
                               "cost_usd": 0.0, "tokens": 0}
        self.events[turn.id] = []

    async def get_turn(self, turn_id: str) -> Turn | None:
        self._check()
        row = self.turns.get(turn_id)
        if row is None:
            return None
        return Turn(id=turn_id, session_id=row["session_id"], message=row["message"],
                    created_at=row["created_at"], status=row["status"],
                    events=sorted(copy.deepcopy(self.events[turn_id]),
                                  key=lambda e: e["sequence"]))

    async def update_turn_status(self, turn_id: str, status: str) -> None:
        self._check()
        if turn_id in self.turns:
            self.turns[turn_id]["status"] = status

    async def record_turn_usage(self, turn_id: str, cost_usd: float, tokens: int) -> None:
        self._check()
        if turn_id in self.turns:
            self.turns[turn_id].update(cost_usd=cost_usd, tokens=tokens)

    async def append_events(
        self, session_id: str, turn_id: str, events: list[dict[str, Any]]
    ) -> None:
        self._check()
        log = self.events[turn_id]
        taken = {e["sequence"] for e in log}
        for event in events:
            if event["sequence"] in taken:
                raise ValueError(f"duplicate sequence {event['sequence']} for {turn_id}")
            log.append(copy.deepcopy(event))
