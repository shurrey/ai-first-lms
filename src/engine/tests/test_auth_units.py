from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from argon2 import PasswordHasher

from engine.auth.capabilities import capabilities_for, has_capability
from engine.auth.config import AuthSettings
from engine.auth.lockout import LoginState, is_locked, may_confirm_success, next_attempt_state
from engine.auth.models import PERSON_ROLES
from engine.auth.passwords import PasswordService
from engine.auth.repository import course_slug
from engine.auth.sessions import SessionManager, _decode_token
from engine.tests.auth_fakes import FakeClock, InMemoryAuthRepository, fast_password_service

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "api.openapi.yaml"


# ---- passwords ---------------------------------------------------------------


def test_hash_is_argon2id_and_verifies():
    pw = fast_password_service()
    hashed = pw.hash("a long enough password")
    assert hashed.startswith("$argon2id$")
    assert pw.verify(hashed, "a long enough password")
    assert not pw.verify(hashed, "wrong password")


def test_verify_returns_false_and_logs_for_malformed_hash(caplog):
    with caplog.at_level(logging.WARNING, logger="engine.auth.passwords"):
        assert fast_password_service().verify("not-a-hash", "anything") is False
    assert "not a valid argon2 hash" in caplog.text


def test_needs_rehash_when_parameters_are_weaker_than_current():
    weak = fast_password_service().hash("pw-pw-pw-pw-pw")
    strong = PasswordService(PasswordHasher(time_cost=2, memory_cost=2048, parallelism=1))
    assert strong.needs_rehash(weak)
    assert not strong.needs_rehash(strong.hash("pw-pw-pw-pw-pw"))


def test_verify_dummy_does_not_raise():
    fast_password_service().verify_dummy("whatever")


# ---- lockout -----------------------------------------------------------------

NOW = datetime(2026, 9, 1, tzinfo=UTC)
FIVE_MIN = timedelta(minutes=5)


def test_attempts_below_max_only_count():
    state = next_attempt_state(LoginState(3, None), NOW, 5, FIVE_MIN)
    assert state == LoginState(4, None)


def test_fifth_attempt_locks_when_reserved():
    state = next_attempt_state(LoginState(4, None), NOW, 5, FIVE_MIN)
    assert state == LoginState(5, NOW + FIVE_MIN)
    assert is_locked(state.locked_until, NOW + timedelta(minutes=4, seconds=59))
    assert not is_locked(state.locked_until, NOW + FIVE_MIN)


def test_no_attempt_is_reserved_during_a_lock():
    locked = LoginState(5, NOW + FIVE_MIN)
    assert next_attempt_state(locked, NOW + timedelta(minutes=1), 5, FIVE_MIN) is None


def test_attempt_after_lock_expiry_restarts_count():
    expired = LoginState(5, NOW - timedelta(seconds=1))
    assert next_attempt_state(expired, NOW, 5, FIVE_MIN) == LoginState(1, None)


def test_success_confirmed_when_unlocked_or_lock_expired():
    reserved = LoginState(2, None)
    assert may_confirm_success(None, reserved, NOW)
    assert may_confirm_success(NOW - timedelta(seconds=1), reserved, NOW)


def test_success_refused_under_a_lock_set_by_another_attempt():
    assert not may_confirm_success(NOW + FIVE_MIN, LoginState(3, None), NOW)
    assert not may_confirm_success(
        NOW + FIVE_MIN, LoginState(5, NOW + timedelta(minutes=4)), NOW
    )


def test_success_confirmed_under_the_lock_its_own_reservation_set():
    own = LoginState(5, NOW + FIVE_MIN)
    assert may_confirm_success(NOW + FIVE_MIN, own, NOW)


# ---- settings ----------------------------------------------------------------


_AUTH_ENV = (
    "SESSION_TTL_HOURS", "COOKIE_SECURE", "LOGIN_MAX_ATTEMPTS", "LOGIN_LOCKOUT_MINUTES",
    "LOGIN_FAILURE_FLOOR_MS",
)


def _tuple(s: AuthSettings) -> tuple[int, bool, int, int, int]:
    return (
        s.session_ttl_hours, s.cookie_secure, s.login_max_attempts, s.login_lockout_minutes,
        s.login_failure_floor_ms,
    )


def test_settings_defaults(monkeypatch):
    for name in _AUTH_ENV:
        monkeypatch.delenv(name, raising=False)
    s = AuthSettings.from_env()
    assert _tuple(s) == (12, False, 5, 5, 250)
    assert s.cookie_max_age == 43200


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_HOURS", "2")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "10")
    monkeypatch.setenv("LOGIN_FAILURE_FLOOR_MS", "0")
    s = AuthSettings.from_env()
    assert _tuple(s) == (2, True, 3, 10, 0)


def test_settings_reject_non_positive(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_HOURS", "0")
    with pytest.raises(ValueError, match="SESSION_TTL_HOURS"):
        AuthSettings.from_env()


# ---- sessions ----------------------------------------------------------------


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo() -> InMemoryAuthRepository:
    return InMemoryAuthRepository()


@pytest.fixture
def manager(repo, clock) -> SessionManager:
    return SessionManager(repo, AuthSettings(), clock)


async def test_create_stores_only_sha256_of_32_byte_token(manager, repo):
    token, record = await manager.create("p1", "student", "pytest")
    raw = _decode_token(token)
    assert raw is not None and len(raw) == 32
    stored = repo.sessions[record.id]
    assert stored.token_hash == hashlib.sha256(raw).digest()
    assert token.encode() not in stored.token_hash
    assert stored.csrf_token and stored.csrf_token != token
    assert stored.expires_at - stored.created_at == timedelta(hours=12)


async def test_lookup_returns_live_session(manager):
    token, record = await manager.create("p1", "student", None)
    found = await manager.lookup(token)
    assert found is not None and found.session.id == record.id and not found.slid


async def test_lookup_rejects_unknown_and_malformed_tokens(manager):
    await manager.create("p1", "student", None)
    assert await manager.lookup("A" * 43) is None
    assert await manager.lookup("not a token!") is None
    assert await manager.lookup("") is None


async def test_lookup_rejects_expired_session(manager, clock):
    token, _ = await manager.create("p1", "student", None)
    clock.advance(hours=12)
    assert await manager.lookup(token) is None


async def test_lookup_rejects_revoked_session(manager):
    token, record = await manager.create("p1", "student", None)
    await manager.revoke(record.id)
    assert await manager.lookup(token) is None


async def test_no_slide_within_a_minute(manager, repo, clock):
    token, record = await manager.create("p1", "student", None)
    clock.advance(seconds=59)
    found = await manager.lookup(token)
    assert found is not None and not found.slid
    assert repo.touch_count == 0
    assert repo.sessions[record.id].expires_at == record.expires_at


async def test_slide_after_a_minute_bumps_last_seen_and_expiry(manager, repo, clock):
    token, record = await manager.create("p1", "student", None)
    clock.advance(minutes=1)
    found = await manager.lookup(token)
    assert found is not None and found.slid
    stored = repo.sessions[record.id]
    assert stored.last_seen_at == clock.now
    assert stored.expires_at == clock.now + timedelta(hours=12)
    assert found.session == stored


async def test_sliding_keeps_an_active_session_alive_past_original_ttl(manager, clock):
    token, _ = await manager.create("p1", "student", None)
    for _ in range(3):
        clock.advance(hours=6)
        assert await manager.lookup(token) is not None


async def test_revoke_others_keeps_the_given_session(manager, repo):
    _, keep = await manager.create("p1", "student", None)
    _, other = await manager.create("p1", "student", None)
    _, someone_else = await manager.create("p2", "student", None)
    await manager.revoke_others("p1", keep.id)
    assert repo.sessions[keep.id].revoked_at is None
    assert repo.sessions[other.id].revoked_at is not None
    assert repo.sessions[someone_else.id].revoked_at is None


# ---- capabilities ------------------------------------------------------------


def _contract_capability_keys() -> set[str]:
    spec = yaml.safe_load(CONTRACT.read_text())
    return set(spec["components"]["schemas"]["Capabilities"]["properties"])


@pytest.mark.parametrize("role", PERSON_ROLES)
def test_capabilities_use_only_contract_keys_and_values(role):
    caps = capabilities_for(role)
    assert set(caps) <= _contract_capability_keys()
    for grant in caps.values():
        assert grant["scope"] in {"self", "own", "program", "assigned", "all"}
        assert grant["access"] in {"full", "read", "summary", "aggregate"}
    assert {"my_data", "notifications"} <= set(caps)


def test_capability_matrix_spot_checks():
    assert "tutor_chat" in capabilities_for("student")
    assert "roster" not in capabilities_for("student")
    assert capabilities_for("faculty")["tutor_chat"]["access"] == "read"
    assert "tutor_chat" not in capabilities_for("program_lead")
    assert capabilities_for("advisor")["roster"]["scope"] == "assigned"
    assert "system_settings" in capabilities_for("admin")
    assert not has_capability("faculty", "system_settings")
    assert has_capability("admin", "badge_revoke") and has_capability("admin", "badge_approve")


def test_capabilities_returns_independent_copies():
    capabilities_for("student")["tutor_chat"]["access"] = "tampered"
    assert capabilities_for("student")["tutor_chat"]["access"] == "full"


# ---- course slug -------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "metadata_slug", "expected"),
    [
        ("CS 101 — Introduction to Computer Science", None, "cs101"),
        ("MATH 201 — Linear Algebra", None, "math201"),
        ("ENG102 Writing", None, "eng102"),
        ("Special Topics: AI & Society", None, "special-topics-ai-society"),
        ("CS 101 — Intro", "intro-cs", "intro-cs"),
    ],
)
def test_course_slug(title, metadata_slug, expected):
    assert course_slug(title, metadata_slug) == expected


def test_only_admins_hold_the_access_log_capability():
    assert has_capability("admin", "access_log")
    assert not any(has_capability(role, "access_log")
                   for role in ("student", "faculty", "program_lead", "advisor"))
