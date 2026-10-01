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

## Corporate Network / TLS Inspection (Zscaler)

On the corporate network, outbound HTTPS (Anthropic, Fish Audio) is re-signed by a corporate
TLS-inspection root CA. Python's bundled CA list (certifi) does not contain it, so every Python
HTTP client is built through the shared helper, which verifies against the OS trust store via
[`truststore`](https://pypi.org/project/truststore/). Certificate verification is always on.

**Off the corporate network:** nothing to do, on the host or in containers.

**On the host (macOS):** nothing to do. `truststore` reads the macOS Keychain, which already
trusts the corporate root.

**In containers:** the images are Debian, so `truststore` reads the container's OpenSSL store,
which does not hold the corporate root. Bake it in at build time:

```bash
# 1. Export the corporate root from the Keychain as PEM. Use the CA's common name as shown
#    in Keychain Access; `security find-certificate -a -c Zscaler | grep labl` lists matches.
mkdir -p certs
security find-certificate -a -c "Zscaler Root CA" -p \
  /Library/Keychains/System.keychain > certs/corporate-root.pem

# 2. Point the build at it (in .env, or exported in your shell).
echo 'CORPORATE_CA_PATH=./certs/corporate-root.pem' >> .env

# 3. Rebuild the Python images (orchestrator, MCP servers, db-seed).
docker compose build orchestrator db-seed mcp-content mcp-roster mcp-assessments \
  mcp-analytics mcp-sis mcp-communications mcp-standards
docker compose up -d
```

How it works: compose passes `CORPORATE_CA_PATH` to `src/engine/Dockerfile` and
`src/data_mcp/Dockerfile` as the BuildKit secret `corporate_ca`. When it is a non-empty PEM, the
build copies it to `/usr/local/share/ca-certificates/corporate-root.crt` and runs
`update-ca-certificates`; a non-PEM file fails the build. The images set
`SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to `/etc/ssl/certs/ca-certificates.crt`. With
`CORPORATE_CA_PATH` unset, compose falls back to the empty `certs/.gitkeep` and no CA is added.
The file may contain several certificates (e.g. root plus intermediate).

- `certs/` is git-ignored except `certs/.gitkeep`, and `*.pem` files are ignored repo-wide.
- Changing `CORPORATE_CA_PATH` triggers a rebuild of the CA layer. Replacing the file's contents
  at the **same** path does not (BuildKit does not hash secrets); use
  `docker compose build --no-cache <service>` after rotating the certificate.
- A plain `docker build` without `--secret id=corporate_ca,src=...` also succeeds, with no CA.

**Escape hatch:** `TLS_INSECURE_SKIP_VERIFY=true` disables verification in the shared HTTP
helper only. It is `false` by default, logs an ERROR on every startup while enabled, and exists so
a broken network day doesn't block a demo. Never commit it as `true`.

**Other tooling behind the proxy:**

- **Node.js:** set `NODE_USE_SYSTEM_CA=1` in the frontend Dockerfiles.
- **Docker pulls:** use ECR mirror images (`public.ecr.aws/docker/library/`) if Docker Hub is
  blocked.

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

## Running Tests Locally

```bash
uv sync --extra dev   # pytest and ruff live in the dev extra
uv run pytest src/engine -q
uv run pytest src/agents -q
```

> **Warning: the data_mcp suite destroys its database.** `src/data_mcp/tests/test_migrations.py`
> runs `DROP SCHEMA public CASCADE` against `LMS_DATABASE_URL`, and `conftest.py` seeds whatever
> that URL points at (its default is the demo's `lms_db`). Always set it to a throwaway database,
> and load the schema first, because the autouse seed fixture queries `persons` before any test runs:
>
> ```bash
> docker exec lms-postgres createdb -U lms lms_test
> docker exec -i lms-postgres psql -U lms -d lms_test -v ON_ERROR_STOP=1 < contracts/db-schema.sql
> LMS_DATABASE_URL=postgresql://lms:lms_dev@localhost:5432/lms_test \
>   uv run pytest src/data_mcp -q
> ```

## Continuous Integration

Workflows live in `.github/workflows/`:

| Workflow | Trigger | What it runs |
|----------|---------|--------------|
| `ci.yaml` | every push and PR to `main` | ruff S608 (string-built SQL), `verify=False` grep, pytest for engine / agents / data_mcp (Postgres service container), Playwright `*.smoke.spec.ts` (Ultra UI, mocked API), `docker compose config` |
| `contract-invariants.yaml` | every push and PR to `main` | `src/platform/ci/scripts/check_contracts.py`, including the migrations-vs-schema check against a Postgres service container |
| `scenario-tests.yaml` | manual (`workflow_dispatch`) | full `docker compose up` plus all scenarios; needs `ANTHROPIC_API_KEY` as a repo secret |

### Make CI a required check on `main`

Branch protection is a GitHub setting, not a file in the repo. A repo admin sets it once:

1. GitHub → **Settings** → **Branches** (or **Rules → Rulesets**) → add a rule for `main`.
2. Enable **Require a pull request before merging** and **Require status checks to pass**.
3. Under required checks, add each job from `ci.yaml` and `contract-invariants.yaml` (they
   appear after the workflows have run once): `ruff-s608`, `no-verify-false`, `test-engine`, `test-agents`, `test-data_mcp`,
   `playwright-smoke`, `compose-config`, `contract-invariants`.
4. Enable **Require branches to be up to date before merging**.

Or with the `gh` CLI (admin token):

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["ruff-s608", "no-verify-false", "test-engine", "test-agents",
                 "test-data_mcp", "playwright-smoke", "compose-config",
                 "contract-invariants"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```
