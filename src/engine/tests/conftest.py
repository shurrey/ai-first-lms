from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER
from engine.tests.auth_fakes import DEMO_PASSWORD, AuthWorld, build_auth_world

AuthedClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture(autouse=True)
def _scheduler_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that need the scheduler set SCHEDULER_ENABLED themselves."""
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")


@pytest.fixture
def auth_world() -> AuthWorld:
    return build_auth_world()


@pytest.fixture
def auth_app(auth_world: AuthWorld):
    return create_app(auth_service=auth_world.service, scope_directory=auth_world.directory)


@pytest.fixture
async def auth_client(auth_app) -> AsyncIterator[AsyncClient]:
    """Anonymous client against an app backed by the in-memory auth repository."""
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def authed_client(auth_app, auth_world: AuthWorld) -> AsyncIterator[AuthedClientFactory]:
    """`await authed_client(role="faculty")` returns a signed-in client.

    `person` names an AuthWorld.people key when it differs from the role (e.g.
    `authed_client("faculty", person="chen")`). The client carries the session
    cookie and sends X-CSRF-Token on every request.
    """
    clients: list[AsyncClient] = []

    async def make(role: str = "student", person: str | None = None) -> AsyncClient:
        person_record = auth_world.people[person or role]
        client = AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test")
        clients.append(client)
        resp = await client.post(
            "/api/auth/login", json={"username": person_record.email, "password": DEMO_PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        if resp.json()["active_role"] != role:
            switched = await client.post("/api/auth/role", json={"role": role})
            assert switched.status_code == 200, switched.text
        return client

    yield make
    for client in clients:
        await client.aclose()
