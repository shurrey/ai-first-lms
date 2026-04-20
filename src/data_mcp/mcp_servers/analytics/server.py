"""Analytics MCP server entry point — SSE transport."""
from __future__ import annotations

import os

import asyncpg
import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from data_mcp.mcp_base import create_mcp_server
from data_mcp.mcp_servers.analytics.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None  # set at startup
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "analytics"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("analytics", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
