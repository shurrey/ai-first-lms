"""Login lockout policy, kept pure so every repository applies it identically."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class LoginState:
    failed_attempts: int
    locked_until: datetime | None


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and locked_until > now


def next_attempt_state(
    current: LoginState, now: datetime, max_attempts: int, lockout: timedelta
) -> LoginState | None:
    """State after reserving one password check, or None while a lock is active.

    The attempt counts as a failure until it is confirmed as a success, so the
    reservation that reaches `max_attempts` sets the lock before its password is
    checked. Once a lock has expired the count restarts.
    """
    if is_locked(current.locked_until, now):
        return None
    base = 0 if current.locked_until is not None else current.failed_attempts
    attempts = base + 1
    if attempts >= max_attempts:
        return LoginState(failed_attempts=attempts, locked_until=now + lockout)
    return LoginState(failed_attempts=attempts, locked_until=None)


def may_confirm_success(
    stored_locked_until: datetime | None, reserved: LoginState, now: datetime
) -> bool:
    """False when a lock is active that this attempt's own reservation did not set."""
    if not is_locked(stored_locked_until, now):
        return True
    return reserved.locked_until is not None and stored_locked_until == reserved.locked_until
