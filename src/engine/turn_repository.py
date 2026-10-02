"""Durable orchestrator records: `sessions`, `turns`, `events_log` and `tool_calls`.

`TurnRepository` is the seam the tool gateway needs; `Persistence` adds what the session
and turn caches (`engine.db`) write through to. `PgTurnRepository` implements both.
Engine turn ids that are not UUIDs (`brief-<session_id>`) are stored under a UUIDv5.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

import asyncpg

from engine.models.session import Session
from engine.models.turn import Turn

ToolCallOutcome = Literal[
    "ok", "denied_permission", "denied_scope", "denied_policy", "gated", "error"
]

_TURN_ID_NAMESPACE = uuid.UUID("0b6f3c1e-6a43-4f8e-9a57-2f1d7c0e5b19")

# In-memory status -> `turns.status`. "pending" and "clarifying" are never written.
_STATUS_TO_DB = {"active": "running", "awaiting_approval": "awaiting_approval",
                 "completed": "done", "error": "error"}
_STATUS_FROM_DB = {"pending": "active", "running": "active", "clarifying": "active",
                   "awaiting_approval": "awaiting_approval", "done": "completed",
                   "error": "error"}
_TERMINAL_DB = ("done", "error")
# Session metadata keys the engine owns; stripped before `Session.metadata` is rebuilt.
_REQUESTER_KEY = "requester_name"
_COURSE_KEY = "course_id"


@dataclass(frozen=True)
class ToolCallRow:
    turn_id: str
    agent: str
    tool: str
    args: dict[str, Any]  # after identity overwrite and PII redaction
    outcome: ToolCallOutcome
    latency_ms: int | None


class TurnRepository(Protocol):
    async def record_tool_call(self, row: ToolCallRow) -> bool:
        """Insert one tool_calls row. False when the turn has no `turns` row."""
        ...


class Persistence(TurnRepository, Protocol):
    async def create_session(self, session: Session) -> None:
        """Idempotent on the session id."""
        ...

    async def get_session(self, session_id: str) -> Session | None: ...

    async def create_turn(self, turn: Turn) -> None: ...

    async def get_turn(self, turn_id: str) -> Turn | None:
        """The turn with every logged event, ordered by sequence."""
        ...

    async def update_turn_status(self, turn_id: str, status: str) -> None: ...

    async def record_turn_usage(self, turn_id: str, cost_usd: float, tokens: int) -> None: ...

    async def append_events(
        self, session_id: str, turn_id: str, events: list[dict[str, Any]]
    ) -> None:
        """Each event carries `event`, `payload`, `sequence` and an ISO `timestamp`."""
        ...


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def turn_db_id(turn_id: str) -> uuid.UUID:
    """The `turns.id` an engine turn id is stored under. Deterministic."""
    return _as_uuid(turn_id) or uuid.uuid5(_TURN_ID_NAMESPACE, turn_id)


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    loaded = json.loads(value) if isinstance(value, str) else value
    return dict(loaded) if isinstance(loaded, dict) else {}


class PgTurnRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_tool_call(self, row: ToolCallRow) -> bool:
        status = await self._pool.execute(
            """
            INSERT INTO tool_calls (turn_id, agent, tool, args, outcome, latency_ms)
            SELECT $1, $2, $3, $4::jsonb, $5, $6
            WHERE EXISTS (SELECT 1 FROM turns WHERE id = $1)
            """,
            turn_db_id(row.turn_id), row.agent, row.tool, json.dumps(row.args, default=str),
            row.outcome, row.latency_ms,
        )
        return bool(status == "INSERT 0 1")

    async def create_session(self, session: Session) -> None:
        session_id = _as_uuid(session.id)
        person_id = _as_uuid(session.person_id or "")
        if session_id is None or person_id is None:
            raise ValueError(f"session {session.id!r} has no UUID id or person")
        course_node = _as_uuid(session.course_id)
        metadata: dict[str, Any] = {**(session.metadata or {}),
                                    _REQUESTER_KEY: session.requester_name}
        if course_node is None:
            metadata[_COURSE_KEY] = session.course_id
        await self._pool.execute(
            """
            INSERT INTO sessions (id, person_id, persona, course_node, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            ON CONFLICT (id) DO NOTHING
            """,
            session_id, person_id, session.persona, course_node,
            json.dumps(metadata, default=str), session.created_at,
        )

    async def get_session(self, session_id: str) -> Session | None:
        sid = _as_uuid(session_id)
        if sid is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT id, person_id, persona, course_node, metadata, created_at"
            " FROM sessions WHERE id = $1",
            sid,
        )
        if row is None:
            return None
        metadata = _json_object(row["metadata"])
        requester = str(metadata.pop(_REQUESTER_KEY, "") or "")
        course = metadata.pop(_COURSE_KEY, None)
        course_id = str(row["course_node"]) if row["course_node"] is not None else course
        return Session(
            id=str(row["id"]),
            persona=row["persona"],
            person_id=str(row["person_id"]),
            course_id=course_id or "all",
            requester_name=requester,
            created_at=row["created_at"],
            metadata=metadata or None,
        )

    async def create_turn(self, turn: Turn) -> None:
        await self._pool.execute(
            """
            INSERT INTO turns (id, session_id, user_message, status, started_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            turn_db_id(turn.id), uuid.UUID(turn.session_id), turn.message,
            _STATUS_TO_DB.get(turn.status, turn.status), turn.created_at,
        )

    async def get_turn(self, turn_id: str) -> Turn | None:
        db_id = turn_db_id(turn_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT session_id, user_message, status, started_at FROM turns WHERE id = $1",
                db_id,
            )
            if row is None:
                return None
            events = await conn.fetch(
                "SELECT sequence, event_type, payload, emitted_at FROM events_log"
                " WHERE turn_id = $1 ORDER BY sequence",
                db_id,
            )
        return Turn(
            id=turn_id,
            session_id=str(row["session_id"]),
            message=row["user_message"],
            created_at=row["started_at"],
            status=_STATUS_FROM_DB.get(row["status"], "active"),
            events=[
                {
                    "event": e["event_type"],
                    "payload": _json_object(e["payload"]),
                    "sequence": e["sequence"],
                    "timestamp": e["emitted_at"].isoformat(timespec="milliseconds"),
                }
                for e in events
            ],
        )

    async def update_turn_status(self, turn_id: str, status: str) -> None:
        db_status = _STATUS_TO_DB.get(status, status)
        await self._pool.execute(
            """
            UPDATE turns SET status = $2,
                   completed_at = CASE WHEN $2 = ANY($3::text[]) THEN now() ELSE NULL END
            WHERE id = $1
            """,
            turn_db_id(turn_id), db_status, list(_TERMINAL_DB),
        )

    async def record_turn_usage(self, turn_id: str, cost_usd: float, tokens: int) -> None:
        await self._pool.execute(
            "UPDATE turns SET cost_usd = $2, tokens = $3 WHERE id = $1",
            turn_db_id(turn_id), cost_usd, tokens,
        )

    async def append_events(
        self, session_id: str, turn_id: str, events: list[dict[str, Any]]
    ) -> None:
        sid = uuid.UUID(session_id)
        db_id = turn_db_id(turn_id)
        await self._pool.executemany(
            """
            INSERT INTO events_log (session_id, turn_id, sequence, event_type, payload, emitted_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            """,
            [
                (sid, db_id, e["sequence"], e["event"],
                 json.dumps(e.get("payload", {}), default=str),
                 datetime.fromisoformat(e["timestamp"]))
                for e in events
            ],
        )
