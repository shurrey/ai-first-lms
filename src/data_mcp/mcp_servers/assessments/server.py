"""Assessments MCP server entry point."""
from __future__ import annotations

import asyncio

import asyncpg
from mcp.server.stdio import stdio_server

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.assessments.tools import get_tools
from data_mcp.settings import settings


async def main() -> None:
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("assessments", get_tools(pool))

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
