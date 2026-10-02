"""Lockout under concurrent password checks, against the in-memory repository."""

from __future__ import annotations

import asyncio
import threading

from engine.auth.config import AuthSettings
from engine.tests.auth_fakes import DEMO_PASSWORD, AuthWorld, build_auth_world

MAX_ATTEMPTS = AuthSettings().login_max_attempts


def _count_real_verifies(world: AuthWorld, person: str) -> list[str]:
    """Records each password checked against `person`'s stored hash (dummy checks excluded)."""
    passwords = world.service.passwords
    stored = world.repo.credentials[world.people[person].id].password_hash
    original = passwords.verify
    seen: list[str] = []

    def verify(password_hash: str, password: str) -> bool:
        if password_hash == stored:
            seen.append(password)
        return original(password_hash, password)

    passwords.verify = verify  # type: ignore[method-assign]
    return seen


async def test_twenty_concurrent_logins_evaluate_at_most_max_attempts_and_stay_locked():
    world = build_auth_world()
    person = world.people["student"]
    verified = _count_real_verifies(world, "student")
    # The right password goes first, so it holds a slot below the one that sets the lock.
    guesses = [DEMO_PASSWORD] + [f"wrong-{i}" for i in range(19)]

    results = await asyncio.gather(
        *(world.service.authenticate(person.email, g) for g in guesses)
    )

    assert len(verified) <= MAX_ATTEMPTS
    assert all(r is None for r in results)
    cred = world.repo.credentials[person.id]
    assert cred.locked_until is not None and cred.locked_until > world.clock.now


async def test_success_finishing_after_a_lock_was_set_is_refused_and_keeps_the_lock():
    world = build_auth_world()
    person = world.people["student"]
    passwords = world.service.passwords
    original = passwords.verify
    right_started = threading.Event()
    release = threading.Event()

    def verify(password_hash: str, password: str) -> bool:
        if password == DEMO_PASSWORD:
            right_started.set()
            release.wait(timeout=5)
        return original(password_hash, password)

    passwords.verify = verify  # type: ignore[method-assign]

    right = asyncio.create_task(world.service.authenticate(person.email, DEMO_PASSWORD))
    while not right_started.is_set():
        await asyncio.sleep(0.001)
    for i in range(MAX_ATTEMPTS):
        assert await world.service.authenticate(person.email, f"wrong-{i}") is None
    locked_until = world.repo.credentials[person.id].locked_until
    assert locked_until is not None

    release.set()
    assert await right is None
    cred = world.repo.credentials[person.id]
    assert cred.locked_until == locked_until
    assert cred.last_login_at is None


async def test_concurrent_password_changes_evaluate_at_most_max_attempts():
    world = build_auth_world()
    verified = _count_real_verifies(world, "student")
    person = world.people["student"]
    _, session = await world.service.sessions.create(person.id, "student", None)
    ctx = await world.service.load_context(session)
    assert ctx is not None

    await asyncio.gather(
        *(world.service.change_password(ctx, f"wrong-{i}", "a brand new passphrase")
          for i in range(20))
    )

    assert len(verified) <= MAX_ATTEMPTS
    assert world.repo.credentials[person.id].locked_until is not None
    assert world.repo.sessions[session.id].revoked_at is not None
