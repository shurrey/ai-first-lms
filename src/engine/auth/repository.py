"""Storage for credentials, auth sessions, persons, enrollments and advisor assignments.

`AuthRepository` is the seam the rest of engine/auth depends on; `PgAuthRepository`
is the asyncpg implementation. All ids cross this boundary as strings.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Protocol

import asyncpg

from engine.auth.lockout import LoginState, may_confirm_success, next_attempt_state
from engine.auth.models import CredentialRecord, EnrollmentRecord, PersonRecord, SessionRecord


class CredentialNotFoundError(LookupError):
    """The person has no credentials row (deleted between lookup and use)."""


_COURSE_CODE = re.compile(r"^\s*([A-Za-z]+)\s*(\d+)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def course_slug(title: str, metadata_slug: str | None) -> str:
    """nodes.metadata.slug when set; otherwise derived from the title.

    "CS 101 — Introduction" becomes "cs101"; a title without a leading course
    code becomes a hyphenated lowercase slug.
    """
    if metadata_slug:
        return metadata_slug
    match = _COURSE_CODE.match(title)
    if match:
        return f"{match.group(1)}{match.group(2)}".lower()
    return _NON_ALNUM.sub("-", title.lower()).strip("-")


class AuthRepository(Protocol):
    async def get_credential_by_username(self, username: str) -> CredentialRecord | None:
        """Case-insensitive lookup."""
        ...

    async def get_credential_by_person(self, person_id: str) -> CredentialRecord | None: ...

    async def reserve_login_attempt(
        self, person_id: str, now: datetime, max_attempts: int, lockout: timedelta
    ) -> LoginState | None:
        """Atomically applies lockout.next_attempt_state; None (and no write) while locked.

        Call before verifying a password, so concurrent guesses each consume a slot.
        Raises CredentialNotFoundError when the person has no credentials row.
        """
        ...

    async def confirm_attempt_success(
        self, person_id: str, reserved: LoginState, now: datetime, *, record_login: bool
    ) -> bool:
        """Atomically resets failed_attempts and locked_until unless a foreign lock is active.

        Returns False, changing nothing, when lockout.may_confirm_success refuses.
        record_login also sets last_login_at.
        """
        ...

    async def update_password(self, person_id: str, password_hash: str) -> None:
        """Also clears must_change."""
        ...

    async def get_person(self, person_id: str) -> PersonRecord | None: ...

    async def list_enrollments(self, person_id: str) -> list[EnrollmentRecord]:
        """Active enrollments in course nodes, ordered by course title."""
        ...

    async def list_advisee_ids(self, advisor_id: str) -> list[str]: ...

    async def create_session(self, session: SessionRecord) -> None: ...

    async def get_session_by_token_hash(self, token_hash: bytes) -> SessionRecord | None:
        """Returns revoked and expired rows too; validity is the caller's decision."""
        ...

    async def touch_session(
        self, session_id: str, last_seen_at: datetime, expires_at: datetime
    ) -> None: ...

    async def set_session_role(self, session_id: str, active_role: str) -> None: ...

    async def revoke_session(self, session_id: str, now: datetime) -> None: ...

    async def revoke_other_sessions(
        self, person_id: str, keep_session_id: str, now: datetime
    ) -> None: ...


def _credential(row: asyncpg.Record) -> CredentialRecord:
    return CredentialRecord(
        person_id=str(row["person_id"]),
        username=row["username"],
        password_hash=row["password_hash"],
        must_change=row["must_change"],
        failed_attempts=row["failed_attempts"],
        locked_until=row["locked_until"],
        last_login_at=row["last_login_at"],
    )


def _session(row: asyncpg.Record) -> SessionRecord:
    return SessionRecord(
        id=str(row["id"]),
        token_hash=bytes(row["token_hash"]),
        person_id=str(row["person_id"]),
        active_role=row["active_role"],
        csrf_token=row["csrf_token"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        user_agent=row["user_agent"],
    )


# username is citext; the parameter is bound as text and cast in SQL so asyncpg
# never needs a citext codec.
_SELECT_CREDENTIALS = (
    "SELECT person_id, username::text AS username, password_hash, must_change, "
    "failed_attempts, locked_until, last_login_at FROM credentials "
)

_SELECT_SESSIONS = (
    "SELECT id, token_hash, person_id, active_role, csrf_token, created_at, "
    "last_seen_at, expires_at, revoked_at, user_agent FROM auth_sessions "
)


class PgAuthRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_credential_by_username(self, username: str) -> CredentialRecord | None:
        row = await self._pool.fetchrow(
            _SELECT_CREDENTIALS + "WHERE username = CAST($1::text AS citext)",
            username,
        )
        return _credential(row) if row else None

    async def get_credential_by_person(self, person_id: str) -> CredentialRecord | None:
        row = await self._pool.fetchrow(
            _SELECT_CREDENTIALS + "WHERE person_id = $1::uuid",
            person_id,
        )
        return _credential(row) if row else None

    async def reserve_login_attempt(
        self, person_id: str, now: datetime, max_attempts: int, lockout: timedelta
    ) -> LoginState | None:
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT failed_attempts, locked_until FROM credentials "
                "WHERE person_id = $1::uuid FOR UPDATE",
                person_id,
            )
            if row is None:
                raise CredentialNotFoundError(person_id)
            state = next_attempt_state(
                LoginState(row["failed_attempts"], row["locked_until"]),
                now,
                max_attempts,
                lockout,
            )
            if state is None:
                return None
            await conn.execute(
                "UPDATE credentials SET failed_attempts = $2, locked_until = $3 "
                "WHERE person_id = $1::uuid",
                person_id,
                state.failed_attempts,
                state.locked_until,
            )
            return state

    async def confirm_attempt_success(
        self, person_id: str, reserved: LoginState, now: datetime, *, record_login: bool
    ) -> bool:
        async with self._pool.acquire() as conn, conn.transaction():
            locked_until = await conn.fetchval(
                "SELECT locked_until FROM credentials WHERE person_id = $1::uuid FOR UPDATE",
                person_id,
            )
            if not may_confirm_success(locked_until, reserved, now):
                return False
            await conn.execute(
                "UPDATE credentials SET failed_attempts = 0, locked_until = NULL, "
                "last_login_at = CASE WHEN $3 THEN $2 ELSE last_login_at END "
                "WHERE person_id = $1::uuid",
                person_id,
                now,
                record_login,
            )
            return True

    async def update_password(self, person_id: str, password_hash: str) -> None:
        await self._pool.execute(
            "UPDATE credentials SET password_hash = $2, must_change = false "
            "WHERE person_id = $1::uuid",
            person_id,
            password_hash,
        )

    async def get_person(self, person_id: str) -> PersonRecord | None:
        row = await self._pool.fetchrow(
            "SELECT id, display_name, email, roles FROM persons WHERE id = $1::uuid",
            person_id,
        )
        if row is None:
            return None
        return PersonRecord(
            id=str(row["id"]),
            display_name=row["display_name"],
            email=row["email"],
            roles=tuple(row["roles"] or ()),
        )

    async def list_enrollments(self, person_id: str) -> list[EnrollmentRecord]:
        rows = await self._pool.fetch(
            "SELECT n.id AS course_id, n.title, n.metadata->>'slug' AS slug, e.role "
            "FROM enrollments e JOIN nodes n ON n.id = e.course_node "
            "WHERE e.person_id = $1::uuid AND e.status = 'active' AND n.kind = 'course' "
            "ORDER BY n.title, e.role",
            person_id,
        )
        return [
            EnrollmentRecord(
                course_id=str(r["course_id"]),
                slug=course_slug(r["title"], r["slug"]),
                title=r["title"],
                role=r["role"],
            )
            for r in rows
        ]

    async def list_advisee_ids(self, advisor_id: str) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT student_id FROM advisor_assignments WHERE advisor_id = $1::uuid",
            advisor_id,
        )
        return [str(r["student_id"]) for r in rows]

    async def create_session(self, session: SessionRecord) -> None:
        await self._pool.execute(
            "INSERT INTO auth_sessions (id, token_hash, person_id, active_role, csrf_token, "
            "created_at, last_seen_at, expires_at, revoked_at, user_agent) "
            "VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, $7, $8, $9, $10)",
            session.id,
            session.token_hash,
            session.person_id,
            session.active_role,
            session.csrf_token,
            session.created_at,
            session.last_seen_at,
            session.expires_at,
            session.revoked_at,
            session.user_agent,
        )

    async def get_session_by_token_hash(self, token_hash: bytes) -> SessionRecord | None:
        row = await self._pool.fetchrow(
            _SELECT_SESSIONS + "WHERE token_hash = $1",
            token_hash,
        )
        return _session(row) if row else None

    async def touch_session(
        self, session_id: str, last_seen_at: datetime, expires_at: datetime
    ) -> None:
        await self._pool.execute(
            "UPDATE auth_sessions SET last_seen_at = $2, expires_at = $3 WHERE id = $1::uuid",
            session_id,
            last_seen_at,
            expires_at,
        )

    async def set_session_role(self, session_id: str, active_role: str) -> None:
        await self._pool.execute(
            "UPDATE auth_sessions SET active_role = $2 WHERE id = $1::uuid",
            session_id,
            active_role,
        )

    async def revoke_session(self, session_id: str, now: datetime) -> None:
        await self._pool.execute(
            "UPDATE auth_sessions SET revoked_at = $2 WHERE id = $1::uuid AND revoked_at IS NULL",
            session_id,
            now,
        )

    async def revoke_other_sessions(
        self, person_id: str, keep_session_id: str, now: datetime
    ) -> None:
        await self._pool.execute(
            "UPDATE auth_sessions SET revoked_at = $3 "
            "WHERE person_id = $1::uuid AND id <> $2::uuid AND revoked_at IS NULL",
            person_id,
            keep_session_id,
            now,
        )


async def create_pool(dsn: str, **kwargs: Any) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, **kwargs)
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")
    return pool
