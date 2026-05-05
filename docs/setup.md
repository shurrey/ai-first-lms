# Setup Guide

## Prerequisites

- Docker and Docker Compose
- An Anthropic API key (Claude API access)
- Optional: Fish Audio API key (for podcast TTS generation)

## Quick Start

### 1. Clone and Configure

```bash
git clone <repo-url>
cd ai-first-lms-prototype
```

Create a `.env` file in the project root:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Database (defaults work for local dev)
POSTGRES_USER=lms
POSTGRES_PASSWORD=lms_dev
POSTGRES_DB=lms_db
POSTGRES_PORT=5432

# Optional — Fish Audio TTS for podcast generation
FISH_AUDIO_API_KEY=
FISH_AUDIO_HOST_VOICE=e3cd384158934cc9a01029cd7d278634
FISH_AUDIO_EXPERT_VOICE=536d3a5e000945adb7038665781a4aca
```

### 2. Build and Start

```bash
docker compose up -d
```

This starts all services:

| Service | Port | Description |
|---------|------|-------------|
| PostgreSQL | 5432 | Database with pgvector |
| MCP Content | 7001 | Content & knowledge graph tools |
| MCP Roster | 7002 | People, enrollments, learner profiles |
| MCP Assessments | 7003 | Grades, attestations, credentials |
| MCP Analytics | 7004 | Learning analytics queries |
| MCP SIS | 7005 | Student information system |
| MCP Communications | 7006 | Messaging tools |
| MCP Standards | 7007 | Educational standards (WCAG, etc.) |
| Orchestrator | 8000 | LangGraph engine + API |
| Chat-First UI | 3000 | Developer/chat-focused frontend |
| Ultra UI | 3100 | Blackboard Ultra-style frontend |
| Grafana | 3001 | Observability dashboards |
| Prometheus | 9090 | Metrics |
| Tempo | 3200 | Distributed tracing |

### 3. Seed Demo Data

The `db-seed` container runs automatically on first start and populates:
- 4 courses (CS 101, MATH 201, ENG 102, BIO 150)
- 50 students, 7 faculty, 1 advisor, 1 admin
- 120 concepts with skill documents (CS 101)
- 14 microcredentials across courses
- 425 grades (294 committed, 131 draft)
- Attestation coverage for demo scenarios

### 4. Access the UIs

- **Chat-First UI:** http://localhost:3000
  - Select a course from the dropdown, pick a persona (Student, Faculty, Advisor, Admin)
  - Chat starts immediately with the AI tutor

- **Ultra UI:** http://localhost:3100
  - Click any course card to enter
  - Switch personas via the sidebar dropdown
  - Click the purple AI fab button (bottom-right) for AI chat

### 5. Verify Everything Works

```bash
# Health check
curl http://localhost:8000/healthz

# Create a session
curl -X POST http://localhost:8000/api/session \
  -H 'Content-Type: application/json' \
  -d '{"persona":"student","course_id":"cs101"}'
```

## Corporate Proxy (Zscaler)

If behind a corporate proxy with SSL inspection:

- **Node.js:** Set `NODE_USE_SYSTEM_CA=1` in frontend Dockerfiles
- **Python:** The orchestrator uses `httpx.AsyncClient(verify=False)` for Anthropic and Fish Audio API calls
- **Docker pulls:** Use ECR mirror images (`public.ecr.aws/docker/library/`) if Docker Hub is blocked

## Rebuilding After Changes

```bash
# Rebuild specific service
docker compose build orchestrator
docker compose up -d orchestrator

# Rebuild everything
docker compose build
docker compose up -d

# Reset database (warning: deletes all data)
docker compose down -v
docker compose up -d
```

## Troubleshooting

**Services won't start:** Check `docker compose logs <service>` for errors. Most common issue is missing `ANTHROPIC_API_KEY` in `.env`.

**MCP tools fail silently:** Check `docker logs lms-mcp-assessments` (or other MCP server). The `TypeError: 'NoneType' object is not callable` errors in MCP logs are harmless SSE disconnect noise.

**Attestations fail:** If you see "Unknown MCP server for tool: attestations.attest", the `attestations` alias in `_MCP_SERVERS` (runner.py) maps to the assessments server.
