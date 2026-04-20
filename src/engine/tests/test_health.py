from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from engine.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz_returns_200(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200


async def test_healthz_body(client):
    resp = await client.get("/healthz")
    assert resp.json() == {"status": "ok"}
