"""Login, context loading and password changes on top of an AuthRepository."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum

from starlette.concurrency import run_in_threadpool

from engine.auth.config import AuthSettings
from engine.auth.lockout import LoginState
from engine.auth.models import PERSON_ROLES, AuthContext, PersonRecord, SessionRecord
from engine.auth.passwords import PasswordService
from engine.auth.repository import AuthRepository, CredentialNotFoundError
from engine.auth.sessions import Clock, SessionManager, utc_now

logger = logging.getLogger(__name__)


def known_roles(roles: tuple[str, ...]) -> tuple[str, ...]:
    """persons.roles filtered to PERSON_ROLES, order preserved."""
    return tuple(r for r in roles if r in PERSON_ROLES)


class PasswordChange(Enum):
    CHANGED = "changed"
    WRONG = "wrong"
    """Wrong current password, or the account was already locked."""
    LOCKED = "locked"
    """This call tripped the lockout; the calling session has been revoked."""


@dataclass
class AuthService:
    repo: AuthRepository
    settings: AuthSettings
    passwords: PasswordService
    clock: Clock = utc_now

    def __post_init__(self) -> None:
        self.sessions = SessionManager(self.repo, self.settings, self.clock)

    async def authenticate(self, username: str, password: str) -> PersonRecord | None:
        """The person on success; None for every failure, with no hint of which.

        Every failure is padded to settings.login_failure_floor_ms, so unknown,
        locked and wrong-password attempts take the same time.
        """
        started = time.monotonic()
        person = await self._authenticate(username, password)
        if person is None:
            await self._pad_failure(started)
        return person

    async def _pad_failure(self, started: float) -> None:
        remaining = self.settings.login_failure_floor_ms / 1000 - (time.monotonic() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _reserve(self, person_id: str) -> LoginState | None:
        """None while locked, or when the credentials row has gone since it was read."""
        try:
            return await self.repo.reserve_login_attempt(
                person_id, self.clock(), self.settings.login_max_attempts, self.settings.lockout
            )
        except CredentialNotFoundError:
            logger.warning("credentials removed during authentication",
                           extra={"person_id": person_id})
            return None

    async def _authenticate(self, username: str, password: str) -> PersonRecord | None:
        # A password is always verified against some hash, even for unknown or locked users.
        cred = await self.repo.get_credential_by_username(username)
        if cred is None:
            await run_in_threadpool(self.passwords.verify_dummy, password)
            return None
        reserved = await self._reserve(cred.person_id)
        if reserved is None:
            await run_in_threadpool(self.passwords.verify_dummy, password)
            logger.info("login rejected: account locked", extra={"person_id": cred.person_id})
            return None
        if not await run_in_threadpool(self.passwords.verify, cred.password_hash, password):
            if reserved.locked_until is not None:
                logger.warning("account locked after failed logins",
                               extra={"person_id": cred.person_id})
            return None
        person = await self.repo.get_person(cred.person_id)
        if person is None or not known_roles(person.roles):
            logger.warning("login rejected: person has no usable role",
                           extra={"person_id": cred.person_id})
            return None
        if not await self.repo.confirm_attempt_success(
            cred.person_id, reserved, self.clock(), record_login=True
        ):
            logger.info("login rejected: account locked during verification",
                        extra={"person_id": cred.person_id})
            return None
        if self.passwords.needs_rehash(cred.password_hash):
            new_hash = await run_in_threadpool(self.passwords.hash, password)
            await self.repo.update_password(cred.person_id, new_hash)
        return person

    async def load_context(self, session: SessionRecord) -> AuthContext | None:
        """None when the person is gone or no longer holds the session's active role."""
        person = await self.repo.get_person(session.person_id)
        if person is None:
            return None
        roles = known_roles(person.roles)
        if session.active_role not in roles:
            return None
        enrollments = await self.repo.list_enrollments(person.id)
        advisees = await self.repo.list_advisee_ids(person.id) if "advisor" in roles else []
        return AuthContext(
            person_id=person.id,
            display_name=person.display_name,
            email=person.email,
            roles=roles,
            active_role=session.active_role,
            enrollments=tuple(enrollments),
            advisee_ids=frozenset(advisees),
            session_id=session.id,
        )

    async def must_change_password(self, person_id: str) -> bool:
        cred = await self.repo.get_credential_by_person(person_id)
        return bool(cred and cred.must_change)

    async def change_password(
        self, ctx: AuthContext, current_password: str, new_password: str
    ) -> PasswordChange:
        """Counts wrong current passwords toward the login lockout.

        When this call trips the lock, ctx's session is revoked and LOCKED is
        returned. On CHANGED, other sessions are revoked. Failures are padded to
        settings.login_failure_floor_ms.
        """
        started = time.monotonic()
        result = await self._change_password(ctx, current_password, new_password)
        if result is not PasswordChange.CHANGED:
            await self._pad_failure(started)
        return result

    async def _change_password(
        self, ctx: AuthContext, current_password: str, new_password: str
    ) -> PasswordChange:
        cred = await self.repo.get_credential_by_person(ctx.person_id)
        if cred is None:
            await run_in_threadpool(self.passwords.verify_dummy, current_password)
            return PasswordChange.WRONG
        reserved = await self._reserve(ctx.person_id)
        if reserved is None:
            await run_in_threadpool(self.passwords.verify_dummy, current_password)
            logger.info("password change rejected: account locked",
                        extra={"person_id": ctx.person_id})
            return PasswordChange.WRONG
        if not await run_in_threadpool(
            self.passwords.verify, cred.password_hash, current_password
        ):
            if reserved.locked_until is None:
                return PasswordChange.WRONG
            logger.warning("account locked after failed password changes; session revoked",
                           extra={"person_id": ctx.person_id})
            await self.sessions.revoke(ctx.session_id)
            return PasswordChange.LOCKED
        if not await self.repo.confirm_attempt_success(
            ctx.person_id, reserved, self.clock(), record_login=False
        ):
            logger.info("password change rejected: account locked during verification",
                        extra={"person_id": ctx.person_id})
            return PasswordChange.WRONG
        new_hash = await run_in_threadpool(self.passwords.hash, new_password)
        await self.repo.update_password(ctx.person_id, new_hash)
        await self.sessions.revoke_others(ctx.person_id, ctx.session_id)
        return PasswordChange.CHANGED
