"""Authentication settings read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

_TRUTHY = {"1", "true", "yes", "on"}

SESSION_COOKIE = "lms_session"
CSRF_COOKIE = "lms_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


def _non_negative_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} must be zero or a positive integer, got {raw!r}")
    return value


@dataclass(frozen=True)
class AuthSettings:
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    login_max_attempts: int = 5
    login_lockout_minutes: int = 5
    # Every failed login takes at least this long, so response time does not reveal
    # whether the username exists or the account is locked.
    login_failure_floor_ms: int = 250

    @property
    def session_ttl(self) -> timedelta:
        return timedelta(hours=self.session_ttl_hours)

    @property
    def cookie_max_age(self) -> int:
        """Cookie Max-Age in seconds."""
        return self.session_ttl_hours * 3600

    @property
    def lockout(self) -> timedelta:
        return timedelta(minutes=self.login_lockout_minutes)

    @classmethod
    def from_env(cls) -> AuthSettings:
        """Raises ValueError on a malformed or non-positive numeric variable."""
        return cls(
            session_ttl_hours=_int_env("SESSION_TTL_HOURS", 12),
            cookie_secure=os.environ.get("COOKIE_SECURE", "false").strip().lower() in _TRUTHY,
            login_max_attempts=_int_env("LOGIN_MAX_ATTEMPTS", 5),
            login_lockout_minutes=_int_env("LOGIN_LOCKOUT_MINUTES", 5),
            login_failure_floor_ms=_non_negative_int_env("LOGIN_FAILURE_FLOOR_MS", 250),
        )
