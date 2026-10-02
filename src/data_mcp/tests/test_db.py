from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from data_mcp import db
from data_mcp.settings import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LMS_DATABASE_URL", "LMS_DB_POOL_MIN", "LMS_DB_POOL_MAX"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.database_url == "postgresql://lms:lms_dev@localhost:5432/lms_db"
    assert s.db_pool_min == 2
    assert s.db_pool_max == 10


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMS_DATABASE_URL", "postgresql://x:x@db:5432/test")
    monkeypatch.setenv("LMS_DB_POOL_MIN", "1")
    monkeypatch.setenv("LMS_DB_POOL_MAX", "5")
    s = Settings()
    assert s.database_url == "postgresql://x:x@db:5432/test"
    assert s.db_pool_min == 1
    assert s.db_pool_max == 5


@pytest.mark.asyncio
async def test_get_pool_creates_pool() -> None:
    mock_pool = AsyncMock()
    mock_create = AsyncMock(return_value=mock_pool)
    with patch("data_mcp.db.asyncpg.create_pool", mock_create):
        db._pool = None  # reset global state
        pool = await db.get_pool()
        assert pool is mock_pool
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_get_pool_returns_same_pool() -> None:
    mock_pool = AsyncMock()
    db._pool = mock_pool
    pool = await db.get_pool()
    assert pool is mock_pool


@pytest.mark.asyncio
async def test_close_pool() -> None:
    mock_pool = AsyncMock()
    db._pool = mock_pool
    await db.close_pool()
    assert db._pool is None
    mock_pool.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_pool_noop_when_none() -> None:
    db._pool = None
    await db.close_pool()  # should not raise
    assert db._pool is None
