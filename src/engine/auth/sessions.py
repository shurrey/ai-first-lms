"""Server-side auth sessions: opaque cookie token, sha256 at rest, sliding expiry."""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from engine.auth.config import AuthSettings
from engine.auth.models import SessionRecord
from engine.auth.repository import AuthRepository

TOKEN_BYTES = 32
SLIDE_INTERVAL = timedelta(minutes=1)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _encode_token(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_token(token: str) -> bytes | None:
    """The raw token bytes, or None when the cookie value is not a well-formed token."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == TOKEN_BYTES else None


def hash_token(raw: bytes) -> bytes:
    return hashlib.sha256(raw).digest()


@dataclass(frozen=True)
class SessionLookup:
    session: SessionRecord
    slid: bool
    """True when this lookup extended the expiry, so the cookies should be re-sent."""


class SessionManager:
    def __init__(
        self, repo: AuthRepository, settings: AuthSettings, clock: Clock = utc_now
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._clock = clock

    async def create(
        self, person_id: str, active_role: str, user_agent: str | None
    ) -> tuple[str, SessionRecord]:
        """Returns (cookie token, stored record). The token itself is never stored."""
        raw = secrets.token_bytes(TOKEN_BYTES)
        now = self._clock()
        record = SessionRecord(
            id=str(uuid.uuid4()),
            token_hash=hash_token(raw),
            person_id=person_id,
            active_role=active_role,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._settings.session_ttl,
            revoked_at=None,
            user_agent=user_agent,
        )
        await self._repo.create_session(record)
        return _encode_token(raw), record

    async def peek(self, token: str) -> SessionRecord | None:
        """The live session for a cookie value without sliding it; None if invalid."""
        raw = _decode_token(token)
        if raw is None:
            return None
        record = await self._repo.get_session_by_token_hash(hash_token(raw))
        if record is None or record.revoked_at is not None:
            return None
        if record.expires_at <= self._clock():
            return None
        return record

    async def lookup(self, token: str) -> SessionLookup | None:
        """Like peek, then slides expiry when last_seen_at is at least a minute old."""
        record = await self.peek(token)
        if record is None:
            return None
        now = self._clock()
        if now - record.last_seen_at < SLIDE_INTERVAL:
            return SessionLookup(record, slid=False)
        expires_at = now + self._settings.session_ttl
        await self._repo.touch_session(record.id, now, expires_at)
        return SessionLookup(replace(record, last_seen_at=now, expires_at=expires_at), slid=True)

    async def revoke(self, session_id: str) -> None:
        await self._repo.revoke_session(session_id, self._clock())

    async def revoke_others(self, person_id: str, keep_session_id: str) -> None:
        await self._repo.revoke_other_sessions(person_id, keep_session_id, self._clock())

    async def set_role(self, session_id: str, active_role: str) -> None:
        await self._repo.set_session_role(session_id, active_role)
