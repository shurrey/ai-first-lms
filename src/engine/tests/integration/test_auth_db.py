"""PgAuthRepository and /api/auth/* against a real Postgres (Alembic head).

Skipped unless ENGINE_TEST_DATABASE_URL is set. Each test creates its own person,
credential and course node and deletes them afterwards.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import threading
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER, AuthSettings
from engine.auth.repository import PgAuthRepository, create_pool
from engine.auth.service import AuthService
from engine.tests.auth_fakes import fast_password_service

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")


@dataclass
class Seeded:
    person_id: str
    advisee_id: str
    course_id: str
    username: str
    password: str


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    assert DSN is not None
    p = await create_pool(DSN)
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def seeded(pool) -> AsyncIterator[Seeded]:
    passwords = fast_password_service()
    tag = uuid.uuid4().hex[:10]
    password = secrets.token_urlsafe(16)
    username = f"auth-it-{tag}@example.test"
    async with pool.acquire() as conn:
        person_id = await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            ["faculty", "program_lead", "advisor"], f"Auth IT {tag}", username,
        )
        advisee_id = await conn.fetchval(
            "INSERT INTO persons (roles, display_name, email) VALUES ($1, $2, $3) RETURNING id",
            ["student"], f"Advisee {tag}", f"advisee-{tag}@example.test",
        )
        course_id = await conn.fetchval(
            "INSERT INTO nodes (kind, title) VALUES ('course', $1) RETURNING id",
            f"ZZ 999 — Auth IT {tag}",
        )
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'faculty')",
            person_id, course_id,
        )
        await conn.execute(
            "INSERT INTO advisor_assignments (advisor_id, student_id) VALUES ($1, $2)",
            person_id, advisee_id,
        )
        await conn.execute(
            "INSERT INTO credentials (person_id, username, password_hash) VALUES ($1, $2, $3)",
            person_id, username, passwords.hash(password),
        )
    try:
        yield Seeded(str(person_id), str(advisee_id), str(course_id), username, password)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])",
                               [person_id, advisee_id])
            await conn.execute("DELETE FROM nodes WHERE id = $1", course_id)


@pytest.fixture
def service(pool) -> AuthService:
    return AuthService(PgAuthRepository(pool), AuthSettings(), fast_password_service())


@pytest.fixture
async def client(service) -> AsyncIterator[AsyncClient]:
    app = create_app(auth_service=service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client: AsyncClient, username: str, password: str):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_login_me_role_switch_logout(client, seeded, pool):
    resp = await _login(client, seeded.username.upper(), seeded.password)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["person"]["id"] == seeded.person_id
    assert body["roles"] == ["faculty", "program_lead", "advisor"]
    assert body["active_role"] == "faculty"
    assert body["enrollments"] == [{
        "course_id": seeded.course_id, "slug": "zz999",
        "title": body["enrollments"][0]["title"], "role": "faculty",
    }]
    assert body["advisees_count"] == 1

    row = await pool.fetchrow(
        "SELECT token_hash, csrf_token, active_role, expires_at - created_at AS ttl "
        "FROM auth_sessions WHERE person_id = $1::uuid", seeded.person_id,
    )
    assert len(row["token_hash"]) == 32
    assert row["csrf_token"] == client.cookies[CSRF_COOKIE]
    assert row["ttl"] == timedelta(hours=12)
    assert await pool.fetchval(
        "SELECT last_login_at IS NOT NULL FROM credentials WHERE person_id = $1::uuid",
        seeded.person_id,
    )

    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
    switched = await client.post("/api/auth/role", json={"role": "program_lead"})
    assert switched.status_code == 200 and switched.json()["active_role"] == "program_lead"
    assert (await client.post("/api/auth/role", json={"role": "admin"})).status_code == 403
    assert (await client.get("/api/auth/me")).json()["active_role"] == "program_lead"

    assert (await client.post("/api/auth/logout")).status_code == 204
    assert await pool.fetchval(
        "SELECT revoked_at IS NOT NULL FROM auth_sessions WHERE person_id = $1::uuid",
        seeded.person_id,
    )
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_lockout_persists_and_is_generic(client, seeded, pool):
    for _ in range(5):
        resp = await _login(client, seeded.username, "wrong")
        assert resp.json() == {"detail": "Invalid username or password."}
    row = await pool.fetchrow(
        "SELECT failed_attempts, locked_until FROM credentials WHERE person_id = $1::uuid",
        seeded.person_id,
    )
    assert row["failed_attempts"] == 5 and row["locked_until"] > datetime.now(UTC)
    locked = await _login(client, seeded.username, seeded.password)
    assert locked.status_code == 401
    assert locked.json() == {"detail": "Invalid username or password."}

    await pool.execute(
        "UPDATE credentials SET locked_until = now() - interval '1 second' "
        "WHERE person_id = $1::uuid", seeded.person_id,
    )
    assert (await _login(client, seeded.username, seeded.password)).status_code == 200


async def test_credentials_deleted_mid_login_get_the_generic_401(seeded, pool):
    class DeletingRepo(PgAuthRepository):
        async def get_credential_by_username(self, username):
            cred = await super().get_credential_by_username(username)
            await pool.execute("DELETE FROM credentials WHERE person_id = $1::uuid",
                               seeded.person_id)
            return cred

    service = AuthService(DeletingRepo(pool), AuthSettings(), fast_password_service())
    app = create_app(auth_service=service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await _login(c, seeded.username, seeded.password)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid username or password."}


async def test_password_change_revokes_other_sessions(service, seeded, pool):
    app = create_app(auth_service=service)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as a,
        AsyncClient(transport=transport, base_url="http://test") as b,
    ):
        await _login(a, seeded.username, seeded.password)
        await _login(b, seeded.username, seeded.password)
        a.headers[CSRF_HEADER] = a.cookies[CSRF_COOKIE]
        new_password = secrets.token_urlsafe(16)
        resp = await a.post(
            "/api/auth/password",
            json={"current_password": seeded.password, "new_password": new_password},
        )
        assert resp.status_code == 204
        assert (await a.get("/api/auth/me")).status_code == 200
        assert (await b.get("/api/auth/me")).status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await _login(c, seeded.username, new_password)).status_code == 200


async def test_lifespan_builds_auth_from_database_url(seeded, monkeypatch):
    assert DSN is not None
    monkeypatch.setenv("DATABASE_URL", DSN)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.db_pool is not None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await _login(c, seeded.username, seeded.password)).status_code == 200
    assert app.state.db_pool is None


async def test_concurrent_guesses_cannot_exceed_max_attempts_or_clear_the_lock(seeded, pool):
    settings = AuthSettings(login_failure_floor_ms=0)
    passwords = fast_password_service()
    service = AuthService(PgAuthRepository(pool), settings, passwords)
    stored = await pool.fetchval(
        "SELECT password_hash FROM credentials WHERE person_id = $1::uuid", seeded.person_id
    )
    original = passwords.verify
    verified: list[str] = []
    slots_taken = asyncio.Event()
    loop = asyncio.get_running_loop()

    def verify(password_hash: str, password: str) -> bool:
        if password_hash == stored:
            verified.append(password)
            if len(verified) >= settings.login_max_attempts:
                loop.call_soon_threadsafe(slots_taken.set)
            time.sleep(0.05)  # argon2-like cost, so guesses overlap
        return original(password_hash, password)

    passwords.verify = verify  # type: ignore[method-assign]

    async def right_guess():
        # Arrives while the wrong guesses are still being verified.
        await asyncio.wait_for(slots_taken.wait(), timeout=10)
        return await service.authenticate(seeded.username, seeded.password)

    results = await asyncio.gather(
        *(service.authenticate(seeded.username, f"wrong-{i}") for i in range(19)),
        right_guess(),
    )

    assert len(verified) <= settings.login_max_attempts
    assert all(r is None for r in results)
    row = await pool.fetchrow(
        "SELECT failed_attempts, locked_until, last_login_at FROM credentials "
        "WHERE person_id = $1::uuid", seeded.person_id,
    )
    assert row["locked_until"] > datetime.now(UTC)
    assert row["failed_attempts"] == settings.login_max_attempts
    assert row["last_login_at"] is None


async def test_success_under_a_lock_set_by_another_guess_is_refused(seeded, pool):
    settings = AuthSettings(login_failure_floor_ms=0)
    passwords = fast_password_service()
    service = AuthService(PgAuthRepository(pool), settings, passwords)
    original = passwords.verify
    right_started = threading.Event()
    release = threading.Event()

    def verify(password_hash: str, password: str) -> bool:
        if password == seeded.password:
            right_started.set()
            release.wait(timeout=10)
        return original(password_hash, password)

    passwords.verify = verify  # type: ignore[method-assign]

    right = asyncio.create_task(service.authenticate(seeded.username, seeded.password))
    while not right_started.is_set():
        await asyncio.sleep(0.005)
    for i in range(settings.login_max_attempts):
        await service.authenticate(seeded.username, f"wrong-{i}")
    locked_until = await pool.fetchval(
        "SELECT locked_until FROM credentials WHERE person_id = $1::uuid", seeded.person_id
    )
    assert locked_until > datetime.now(UTC)

    release.set()
    assert await right is None
    assert await pool.fetchval(
        "SELECT locked_until FROM credentials WHERE person_id = $1::uuid", seeded.person_id
    ) == locked_until


async def test_wrong_current_passwords_lock_and_revoke_the_session(client, seeded, pool):
    await _login(client, seeded.username, seeded.password)
    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
    body = {"current_password": "wrong", "new_password": secrets.token_urlsafe(16)}
    for _ in range(4):
        assert (await client.post("/api/auth/password", json=body)).status_code == 400
    assert (await client.post("/api/auth/password", json=body)).status_code == 401
    row = await pool.fetchrow(
        "SELECT c.locked_until, s.revoked_at FROM credentials c "
        "JOIN auth_sessions s ON s.person_id = c.person_id WHERE c.person_id = $1::uuid",
        seeded.person_id,
    )
    assert row["locked_until"] > datetime.now(UTC) and row["revoked_at"] is not None
    assert (await _login(client, seeded.username, seeded.password)).status_code == 401
