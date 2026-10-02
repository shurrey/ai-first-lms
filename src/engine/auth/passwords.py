"""Argon2id password hashing.

Verification is CPU-bound (tens of milliseconds); async callers should run these
methods in a worker thread.
"""

from __future__ import annotations

import logging
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

logger = logging.getLogger(__name__)


class PasswordService:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()
        # Verified against when the username is unknown, so a miss costs the same as a hit.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """False on mismatch or on a malformed stored hash; never raises for either."""
        try:
            return self._hasher.verify(password_hash, password)
        except VerificationError:
            return False
        except InvalidHashError:
            logger.warning("stored password hash is not a valid argon2 hash")
            return False

    def verify_dummy(self, password: str) -> None:
        self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)
