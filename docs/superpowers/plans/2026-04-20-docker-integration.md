# Docker Integration — Replace Stubs with Real Services

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update docker-compose.yaml to build and run the real engine, MCP server, and frontend implementations instead of stubs.

**Architecture:** Three Dockerfiles (engine, data_mcp, frontend) replace three stub build contexts. The 7 MCP servers share one Docker image with per-container commands. Each MCP server switches from stdio to SSE HTTP transport. A one-shot seed service populates demo data.

**Tech Stack:** Docker, docker-compose, Python 3.12, Node 20, FastAPI, MCP SDK (SSE transport), Next.js, pnpm, asyncpg, uvicorn

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/engine/Dockerfile` | Build engine (FastAPI orchestrator) |
| Create | `src/data_mcp/Dockerfile` | Build MCP servers (shared image, per-container command) |
| Create | `src/frontend/Dockerfile` | Build frontend (Next.js) |
| Create | `src/frontend/.dockerignore` | Exclude node_modules from build context |
| Modify | `src/data_mcp/mcp_servers/content/server.py` | Switch to SSE transport + healthz |
| Modify | `src/data_mcp/mcp_servers/roster/server.py` | Switch to SSE transport + healthz |
| Modify | `src/data_mcp/mcp_servers/assessments/server.py` | Switch to SSE transport + healthz |
| Modify | `src/data_mcp/mcp_servers/analytics/server.py` | Switch to SSE transport + healthz |
| Modify | `src/data_mcp/mcp_servers/sis/server.py` | Switch to SSE transport + healthz |
| Modify | `src/data_mcp/mcp_servers/communications/server.py` | Switch to SSE transport + healthz |
| Modify | `src/data_mcp/mcp_servers/standards/server.py` | Switch to SSE transport + healthz |
| Modify | `pyproject.toml` | Merge dependencies from engine + data workstreams |
| Modify | `docker-compose.yaml` | Point at real build contexts, add seed service |
| Modify | `src/frontend/next.config.ts` | Add `output: "standalone"` for Docker |

---

### Task 1: Merge pyproject.toml Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml with merged dependencies**

Replace the entire `pyproject.toml` with a unified version that includes dependencies from both engine and data workstreams:

```toml
[project]
name = "ai-first-lms"
version = "0.1.0"
description = "AI-First LMS Prototype — Engine + Data/MCP"
requires-python = ">=3.12"
dependencies = [
    # Engine
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "sse-starlette>=2.0",
    "pyyaml>=6.0",
    "langgraph>=0.2",
    "anthropic>=0.30",
    "structlog>=24.0",
    "opentelemetry-api>=1.24",
    "opentelemetry-sdk>=1.24",
    "opentelemetry-instrumentation-fastapi>=0.45b0",
    "opentelemetry-exporter-otlp>=1.24",
    # Data / MCP
    "asyncpg>=0.29.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "alembic>=1.13.0",
    "pgvector>=0.3.0",
    "mcp>=1.0.0",
    "psycopg2-binary>=2.9.9",
    # MCP SSE transport (uses starlette internally)
    "starlette>=0.37",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "ruff>=0.4",
    "mypy>=1.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/engine", "src/data_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["src/engine/tests", "src/data_mcp/tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "feat: merge engine + data deps into unified pyproject.toml"
```

---

### Task 2: Switch MCP Servers from stdio to SSE Transport

All 7 servers follow the identical pattern. Each `server.py` becomes a Starlette app with SSE transport and a `/healthz` endpoint, run via uvicorn on the `PORT` env var.

**Files:**
- Modify: `src/data_mcp/mcp_servers/content/server.py`
- Modify: `src/data_mcp/mcp_servers/roster/server.py`
- Modify: `src/data_mcp/mcp_servers/assessments/server.py`
- Modify: `src/data_mcp/mcp_servers/analytics/server.py`
- Modify: `src/data_mcp/mcp_servers/sis/server.py`
- Modify: `src/data_mcp/mcp_servers/communications/server.py`
- Modify: `src/data_mcp/mcp_servers/standards/server.py`

- [ ] **Step 1: Update content server**

Replace `src/data_mcp/mcp_servers/content/server.py` entirely:

```python
"""Content MCP server entry point — SSE transport."""
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
from data_mcp.mcp_servers.content.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None  # set at startup
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "content"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("content", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 2: Update roster server**

Replace `src/data_mcp/mcp_servers/roster/server.py` — identical pattern, change `"content"` → `"roster"`, tools import, default port `7002`:

```python
"""Roster MCP server entry point — SSE transport."""
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
from data_mcp.mcp_servers.roster.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "roster"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("roster", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 3: Update assessments server**

Replace `src/data_mcp/mcp_servers/assessments/server.py` — same pattern, `"assessments"`, default port `7003`:

```python
"""Assessments MCP server entry point — SSE transport."""
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
from data_mcp.mcp_servers.assessments.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "assessments"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("assessments", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7003"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 4: Update analytics server**

Replace `src/data_mcp/mcp_servers/analytics/server.py` — `"analytics"`, default port `7004`:

```python
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

server: object = None
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
```

- [ ] **Step 5: Update sis server**

Replace `src/data_mcp/mcp_servers/sis/server.py` — `"sis"`, default port `7005`:

```python
"""SIS MCP server entry point — SSE transport."""
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
from data_mcp.mcp_servers.sis.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "sis"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("sis", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7005"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 6: Update communications server**

Replace `src/data_mcp/mcp_servers/communications/server.py` — `"communications"`, default port `7006`:

```python
"""Communications MCP server entry point — SSE transport."""
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
from data_mcp.mcp_servers.communications.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "communications"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("communications", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7006"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 7: Update standards server**

Replace `src/data_mcp/mcp_servers/standards/server.py` — `"standards"`, default port `7007`:

```python
"""Standards MCP server entry point — SSE transport."""
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
from data_mcp.mcp_servers.standards.tools import get_tools
from data_mcp.settings import settings

sse = SseServerTransport("/messages/")

server: object = None
pool: asyncpg.Pool | None = None


async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "standards"})


async def on_startup():
    global server, pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    server = create_mcp_server("standards", get_tools(pool))


app = Starlette(
    routes=[
        Route("/healthz", endpoint=healthz),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    on_startup=[on_startup],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7007"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 8: Commit all server changes**

```bash
git add src/data_mcp/mcp_servers/*/server.py
git commit -m "feat(data-mcp): switch all 7 MCP servers from stdio to SSE transport"
```

---

### Task 3: Create Engine Dockerfile

**Files:**
- Create: `src/engine/Dockerfile`

- [ ] **Step 1: Create the Dockerfile**

Create `src/engine/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install build deps for asyncpg etc.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy engine source
COPY src/engine/ /app/engine/

# Copy contracts (needed for manifest loading)
COPY contracts/ /app/contracts/

# Copy agents source (engine imports agent manifests)
COPY src/agents/ /app/agents/

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "engine.__main__:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Commit**

```bash
git add src/engine/Dockerfile
git commit -m "feat(engine): add Dockerfile for orchestrator service"
```

---

### Task 4: Create Data/MCP Dockerfile

**Files:**
- Create: `src/data_mcp/Dockerfile`

- [ ] **Step 1: Create the Dockerfile**

Create `src/data_mcp/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy data_mcp source
COPY src/data_mcp/ /app/data_mcp/

ENV PYTHONPATH=/app

# Default; overridden per-container via docker-compose command
CMD ["python", "-m", "data_mcp.mcp_servers.content.server"]
```

- [ ] **Step 2: Commit**

```bash
git add src/data_mcp/Dockerfile
git commit -m "feat(data-mcp): add Dockerfile for MCP server containers"
```

---

### Task 5: Create Frontend Dockerfile

**Files:**
- Create: `src/frontend/Dockerfile`
- Create: `src/frontend/.dockerignore`
- Modify: `src/frontend/next.config.ts`

- [ ] **Step 1: Add standalone output to next.config.ts**

Replace `src/frontend/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
```

- [ ] **Step 2: Create .dockerignore**

Create `src/frontend/.dockerignore`:

```
node_modules
.next
.env*
```

- [ ] **Step 3: Create the Dockerfile**

Create `src/frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine AS base

RUN corepack enable && corepack prepare pnpm@latest --activate

# --- Dependencies ---
FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- Build ---
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# --- Runtime ---
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
```

- [ ] **Step 4: Commit**

```bash
git add src/frontend/Dockerfile src/frontend/.dockerignore src/frontend/next.config.ts
git commit -m "feat(frontend): add Dockerfile and standalone output config"
```

---

### Task 6: Update docker-compose.yaml

**Files:**
- Modify: `docker-compose.yaml`

- [ ] **Step 1: Replace the full docker-compose.yaml**

The key changes:
- `orchestrator.build` → `context: .` with `dockerfile: src/engine/Dockerfile`
- `frontend.build` → `context: src/frontend`
- All `mcp-*` → `build.context: .` with `dockerfile: src/data_mcp/Dockerfile`, per-service `command`
- Add `DATABASE_URL` to all MCP services
- Add `db-seed` one-shot service
- Keep the observability stack untouched

Replace `docker-compose.yaml`:

```yaml
# docker-compose.yaml — AI-First LMS Prototype
# Owned by Platform workstream (T-P-*)
# Usage: docker compose up
# Docs: src/platform/README.md

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: lms-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-lms}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-lms_dev}
      POSTGRES_DB: ${POSTGRES_DB:-lms_db}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./contracts/db-schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-lms} -d ${POSTGRES_DB:-lms_db}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    restart: unless-stopped

  # --- MCP servers (real implementations via SSE transport) ---

  mcp-content:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.content.server:app", "--host", "0.0.0.0", "--port", "7001"]
    container_name: lms-mcp-content
    environment:
      PORT: "7001"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_CONTENT_PORT:-7001}:7001"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7001/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  mcp-roster:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.roster.server:app", "--host", "0.0.0.0", "--port", "7002"]
    container_name: lms-mcp-roster
    environment:
      PORT: "7002"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_ROSTER_PORT:-7002}:7002"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7002/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  mcp-assessments:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.assessments.server:app", "--host", "0.0.0.0", "--port", "7003"]
    container_name: lms-mcp-assessments
    environment:
      PORT: "7003"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_ASSESSMENTS_PORT:-7003}:7003"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7003/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  mcp-analytics:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.analytics.server:app", "--host", "0.0.0.0", "--port", "7004"]
    container_name: lms-mcp-analytics
    environment:
      PORT: "7004"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_ANALYTICS_PORT:-7004}:7004"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7004/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  mcp-sis:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.sis.server:app", "--host", "0.0.0.0", "--port", "7005"]
    container_name: lms-mcp-sis
    environment:
      PORT: "7005"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_SIS_PORT:-7005}:7005"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7005/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  mcp-communications:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.communications.server:app", "--host", "0.0.0.0", "--port", "7006"]
    container_name: lms-mcp-communications
    environment:
      PORT: "7006"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_COMMUNICATIONS_PORT:-7006}:7006"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7006/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  mcp-standards:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    command: ["uvicorn", "data_mcp.mcp_servers.standards.server:app", "--host", "0.0.0.0", "--port", "7007"]
    container_name: lms-mcp-standards
    environment:
      PORT: "7007"
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    ports:
      - "${MCP_STANDARDS_PORT:-7007}:7007"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:7007/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # --- Orchestrator (real Engine implementation) ---

  orchestrator:
    build:
      context: .
      dockerfile: src/engine/Dockerfile
    container_name: lms-orchestrator
    environment:
      PORT: "8000"
      DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
    ports:
      - "${ORCHESTRATOR_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')\""]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # --- Frontend (real Next.js implementation) ---

  frontend:
    build: src/frontend
    container_name: lms-frontend
    environment:
      PORT: "3000"
      NEXT_PUBLIC_API_URL: http://orchestrator:8000
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    depends_on:
      orchestrator:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:3000/ || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # --- Database seed (one-shot) ---

  db-seed:
    build:
      context: .
      dockerfile: src/data_mcp/Dockerfile
    container_name: lms-db-seed
    command: ["python", "-m", "data_mcp.seed.cs101", "--seed", "42"]
    environment:
      LMS_DATABASE_URL: postgresql://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD:-lms_dev}@postgres:5432/${POSTGRES_DB:-lms_db}
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  # --- Observability ---

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.96.0
    container_name: lms-otel-collector
    command: ["--config=/etc/otel/config.yaml"]
    volumes:
      - ./src/platform/otel/collector-config.yaml:/etc/otel/config.yaml:ro
    ports:
      - "${OTEL_GRPC_PORT:-4317}:4317"
      - "${OTEL_HTTP_PORT:-4318}:4318"
      - "8889:8889"
    depends_on:
      - tempo
    restart: unless-stopped

  tempo:
    image: grafana/tempo:2.4.1
    container_name: lms-tempo
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./src/platform/otel/tempo-config.yaml:/etc/tempo.yaml:ro
      - tempo-data:/var/tempo
    ports:
      - "3200:3200"

  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: lms-prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--web.enable-remote-write-receiver"
    volumes:
      - ./src/platform/otel/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:10.4.1
    container_name: lms-grafana
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
    volumes:
      - ./src/platform/otel/grafana-provisioning:/etc/grafana/provisioning:ro
      - ./src/platform/otel/grafana-dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    ports:
      - "${GRAFANA_PORT:-3001}:3000"
    depends_on:
      - tempo
      - prometheus
    restart: unless-stopped

volumes:
  pgdata:
  tempo-data:
  prometheus-data:
  grafana-data:
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yaml
git commit -m "feat(platform): replace all stubs with real service builds in docker-compose"
```

---

### Task 7: Smoke Test

- [ ] **Step 1: Clean start**

```bash
docker compose down -v
```

- [ ] **Step 2: Build and start all services**

```bash
docker compose up --build -d
```

- [ ] **Step 3: Wait for services and check health**

```bash
# Wait ~30s for builds and startup, then:
docker compose ps
```

Expected: all services show "healthy" or "Up" (db-seed will show "Exited (0)")

- [ ] **Step 4: Check orchestrator health**

```bash
curl http://localhost:8000/healthz
```

Expected: `{"status":"ok"}` (not `{"status":"ok","stub":true}`)

- [ ] **Step 5: Check MCP server health**

```bash
curl http://localhost:7001/healthz
curl http://localhost:7002/healthz
```

Expected: `{"status":"ok","server":"content"}` and `{"status":"ok","server":"roster"}`

- [ ] **Step 6: Check frontend**

```bash
curl -s http://localhost:3000 | head -20
```

Expected: HTML containing Next.js app (not "Stub Frontend")

- [ ] **Step 7: Check seed ran**

```bash
docker compose logs db-seed
```

Expected: seed output showing data insertion, exit code 0

- [ ] **Step 8: Fix any issues, then commit if changes needed**

If any service fails to start, check `docker compose logs <service>` and fix. Common issues:
- Missing env vars → check `LMS_DATABASE_URL` vs `DATABASE_URL` prefix
- Import errors → check `PYTHONPATH` in Dockerfile
- Port conflicts → check no local services on 3000/7001-7007/8000
