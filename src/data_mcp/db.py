from __future__ import annotations

import asyncpg

from data_mcp.settings import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return a shared asyncpg connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
        )
    return _pool


async def close_pool() -> None:
    """Close the shared pool if it exists."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
