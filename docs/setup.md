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
# Password for every seeded account; compose will not start without it
SEED_DEMO_PASSWORD=<pick-a-password>

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

`.env.example` lists every variable with its default (optional ones, such as `CORPORATE_CA_PATH`, are commented out); `cp .env.example .env` is the quickest start.

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
- A login for every seeded person (see [Signing In](#signing-in))

### 4. Access the UIs

- **Chat-First UI:** http://localhost:3000
- **Ultra UI:** http://localhost:3100
  - Click any course card to enter
  - Click the purple AI fab button (bottom-right) for AI chat

Both UIs open on a sign-in page. What you see after signing in depends on the person's
roles and enrollments.

### Signing In

- **Accounts come from the seed.** Every seeded person (50 students, the faculty, the
  advisor and the admin) has a login. The username is the person's email.
- **The password is `SEED_DEMO_PASSWORD`** from your `.env`, the same for every account.
  It is never written to the database in plain text, printed, or logged.
- **List the accounts** with `src/platform/scripts/demo-accounts` (add `--all` for everyone).
  It reads `LMS_DATABASE_URL`, defaulting to the compose database on `localhost:5432`.

| Person | Username | Roles |
|---|---|---|
| Emma Smith | `emma.smith@student.edu` | student |
| Noah Brown | `noah.brown@student.edu` | student |
| Dr. Maria Torres | `m.torres@university.edu` | faculty, program_lead |
| Dr. Sarah Chen | `s.chen@university.edu` | faculty |
| Dr. Emily Watson | `e.watson@university.edu` | faculty |
| Dr. Michael Patel | `m.patel@university.edu` | faculty |
| Ms. Adaeze Okafor | `a.okafor@university.edu` | advisor |
| Dr. Richard Hayes | `r.hayes@university.edu` | admin |

- **One login works on both UIs.** Cookies are scoped to the host, not the port, so after
  signing in on http://localhost:3000, http://localhost:3100 is already signed in as the same
  person (and vice versa). Use `localhost` for both; `127.0.0.1` is a different cookie host.
- **Any other web app on `localhost` shares those cookies.** A service on any other port
  receives `lms_session` with every request and can read `lms_csrf` from JavaScript, which is
  enough to act as the signed-in user. Don't run untrusted local web apps alongside the demo.
- **Keep `COOKIE_SECURE=false` for plain `http://localhost`.** With `true` the browser drops
  the session cookie over HTTP and every sign-in appears to fail. Set it to `true` only behind HTTPS.
- **Lockout:** `LOGIN_MAX_ATTEMPTS` (default 5) wrong passwords in a row lock the account for
  `LOGIN_LOCKOUT_MINUTES` (default 5). The error message is the same either way.
- Sessions last `SESSION_TTL_HOURS` (default 12) and slide while in use.
- **Set `PII_PSEUDONYM_SALT`** to any random string. Agents see learners as `Student-` plus 8
  hex characters; without the salt the engine picks a random one per process (and logs a
  warning), so pseudonyms change on every restart.
- Changing `SEED_DEMO_PASSWORD` takes effect on the next seed run:
  `docker compose run --rm db-seed`.

### 5. Verify Everything Works

```bash
# Health check
curl http://localhost:8000/healthz

# Sign in as Emma (stores lms_session and lms_csrf in a cookie jar)
set -a; . ./.env; set +a
curl -c /tmp/lms.cookies -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"emma.smith@student.edu\",\"password\":\"$SEED_DEMO_PASSWORD\"}"

# Create a session; non-GET requests need X-CSRF-Token = the lms_csrf cookie
CSRF=$(awk '$6=="lms_csrf"{print $7}' /tmp/lms.cookies)
curl -b /tmp/lms.cookies -X POST http://localhost:8000/api/session \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
  -d '{"course_id":"cs101"}'

# Run a scripted scenario end to end (it signs in as the scenario's login_as)
uv run python src/platform/scripts/demo 1 --check
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

**`required variable SEED_DEMO_PASSWORD is missing a value`:** add `SEED_DEMO_PASSWORD` to `.env` (see `.env.example`).

**Sign-in always fails on http://localhost:** check `COOKIE_SECURE=false` in `.env`, then `docker compose up -d orchestrator`. If the password is right but sign-in still fails, the account may be locked for `LOGIN_LOCKOUT_MINUTES`.

**`scripts/demo` says `SEED_DEMO_PASSWORD is not set`:** it reads the shell environment, not `.env`. Run `set -a; . ./.env; set +a` first.

**MCP tools fail silently:** Check `docker logs lms-mcp-assessments` (or other MCP server). The `TypeError: 'NoneType' object is not callable` errors in MCP logs are harmless SSE disconnect noise.

**Attestations fail:** If you see "Unknown MCP server for tool: attestations.attest", the `attestations` alias in `_MCP_SERVERS` (runner.py) maps to the assessments server.

## Running Tests Locally

```bash
uv sync --extra dev   # pytest and ruff live in the dev extra
uv run pytest src/engine -q
uv run pytest src/agents -q
uv run pytest src/platform/smoke-tests -q   # scenario executor
uv run python src/platform/ci/language_lint.py   # banned terms in prompts and UI copy
uv run pytest src/platform/ci/tests -q            # CI checkers, incl. the language lint
```

`language_lint.py` reads its term list from the yaml block in `docs/language.md` and flags
those terms (whole word, case-insensitive except entries under `case_sensitive`) in every
`src/**/system_prompt.md`, in prompt text embedded in `src/engine/**/*.py` (strings assigned
to names ending in `PROMPT`, `PROMPTS`, `ADDENDUM`, `INSTRUCTION` or `INSTRUCTIONS`, strings that
reach `system=` of a `.messages.create` or `.messages.stream` call, and the module-level strings
either one references by name), and in the user-visible strings of both UIs' `.tsx`
files: JSX text, string and template literals, and copy attributes such as `aria-label` or
`placeholder`.
Identifiers, imports, comments, `className`/`data-*` values and all-lowercase keys such as
`"thinking"` are ignored, as are test files. For a legitimate use (quoted student speech, a
person rather than the software), reword if you can; otherwise add an entry with `path`,
`term`, `reason` and optionally `line_contains` to `src/platform/ci/language_allowlist.yaml`.

DB-backed engine tests skip unless `ENGINE_TEST_DATABASE_URL` is set. Point it at a
throwaway database built with the migrations, never at the demo's `lms_db`:

```bash
LMS_DATABASE_URL=postgresql://lms:lms_dev@localhost:5432/lms_test uv run alembic upgrade head
ENGINE_TEST_DATABASE_URL=postgresql://lms:lms_dev@localhost:5432/lms_test uv run pytest src/engine -q
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

## Measurement and Scheduled Jobs

These orchestrator settings come from `.env` (defaults in `.env.example`) and are passed
through by `docker-compose.yaml`. Restart the orchestrator after changing one.

| Variable | Default | Meaning |
|----------|---------|---------|
| `MEASURE_WINDOW_DAYS` | `14` | Days after an AI action during which a student's next evidence or attestation on the same node or criterion is linked to it as an outcome (spec §6.4) |
| `SCHEDULER_ENABLED` | `true` | Runs the in-process scheduler for periodic jobs such as the outcome linker; `false` stops them all |
| `OUTCOME_LINKER_INTERVAL_MINUTES` | `15` | How often the outcome linker runs |

## Recording and Replaying Scenario Fixtures

Scenario runs and the live-login Playwright specs can use recorded model responses instead
of the Anthropic API, so they need no API key and cost nothing. Three orchestrator variables
control it:

| Variable | Default | Meaning |
|----------|---------|---------|
| `LLM_FIXTURE_MODE` | `off` | `off` calls the API; `record` calls it and saves every response; `replay` answers from saved responses and makes no API calls |
| `LLM_FIXTURE_DIR` | empty | Where fixtures are read and written, as a path inside the orchestrator container. Required when the mode is `record` or `replay`; the orchestrator fails the turn without it |
| `LLM_FIXTURE_ALLOW` | empty | Must be `1` when the mode is `record` or `replay`, confirming a test environment; otherwise the orchestrator refuses to start. The fixtures overlay sets it |

A fixture only matches a request made against the same database state, so recording and
replay both run through `src/platform/llm-fixtures/run-live-e2e record|replay`. It starts a
separate compose project (`lms-llm-fixtures`) with fresh volumes and a fresh seed, sets
`LLM_FIXTURE_DIR` and `LLM_FIXTURE_ALLOW=1`, runs the live Chat UI specs and then
`scripts/demo all --check`. It never touches the demo database. See `src/platform/llm-fixtures/README.md` for the exact steps.

A recorded set replays only on the day it was recorded: several MCP tools filter on `now()`
against the seed's absolute dates (fixed clock: T-P-106). Until that lands,
`src/platform/llm-fixtures/recordings/` is git-ignored, nothing in it is committed, and CI's
`e2e-live-replay` job runs only when the CI workflow is started by hand with the run id of a
same-day **Record LLM Fixtures** run.

Re-record after changing a prompt, a manifest, a tool schema, the seed or a scenario.

## Continuous Integration

Workflows live in `.github/workflows/`:

| Workflow | Trigger | What it runs |
|----------|---------|--------------|
| `ci.yaml` | every push and PR to `main`; manual (`workflow_dispatch`, needs `fixtures_run_id`) | ruff S608 (string-built SQL), `verify=False` grep, language lint (`src/platform/ci/language_lint.py` and its tests), pytest for engine (DB-backed tests against an alembic-built Postgres service) / agents / data_mcp (Postgres service container) / scenario executor, Playwright `*.smoke.spec.ts` for both the Ultra UI and the Chat UI (mocked API; `playwright-smoke` passes only when both do), `docker compose config`; on a manual run only, `e2e-live-replay` (full stack replaying the `llm-fixtures` artifact of the Record LLM Fixtures run given as `fixtures_run_id` through the live Chat UI specs and `scripts/demo all --check`) |
| `contract-invariants.yaml` | every push and PR to `main` | `src/platform/ci/scripts/check_contracts.py`, including the migrations-vs-schema check against a Postgres service container, then `pytest src/platform/ci/tests` |
| `record-llm-fixtures.yaml` | manual (`workflow_dispatch`) | `run-live-e2e record`; uploads the recorded fixtures as the `llm-fixtures` artifact for a same-day manual CI run to replay; needs `ANTHROPIC_API_KEY` as a repo secret |
| `scenario-tests.yaml` | manual (`workflow_dispatch`) | full `docker compose up` plus all scenarios; needs `ANTHROPIC_API_KEY` as a repo secret |

Jobs that need `SEED_DEMO_PASSWORD` take it from the `SEED_DEMO_PASSWORD` repo secret when one is set, otherwise generate a random one at job start. Never put a literal value in a workflow; `src/platform/ci/tests/test_workflows.py` fails if one appears.

### Make CI a required check on `main`

Branch protection is a GitHub setting, not a file in the repo. A repo admin sets it once:

1. GitHub → **Settings** → **Branches** (or **Rules → Rulesets**) → add a rule for `main`.
2. Enable **Require a pull request before merging** and **Require status checks to pass**.
3. Under required checks, add each job from `ci.yaml` and `contract-invariants.yaml` (they
   appear after the workflows have run once): `ruff-s608`, `no-verify-false`, `language-lint`, `test-engine`, `test-agents`, `test-data_mcp`,
   `test-platform`, `playwright-smoke`, `compose-config`, `contract-invariants`.
4. Enable **Require branches to be up to date before merging**.

Or with the `gh` CLI (admin token):

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["ruff-s608", "no-verify-false", "language-lint", "test-engine", "test-agents",
                 "test-data_mcp", "test-platform", "playwright-smoke", "compose-config",
                 "contract-invariants"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```
