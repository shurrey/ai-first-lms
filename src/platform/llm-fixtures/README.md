# Recorded LLM fixtures

`recordings/` holds the orchestrator's recorded Anthropic responses, one JSON file per request
(engine side: `src/engine/llm_fixture.py`). With them, the full stack runs the live Chat UI
scenario specs and `scripts/demo all --check` with no API key and no model cost. CI's
`e2e-live-replay` job (`.github/workflows/ci.yaml`) does exactly that.

`recordings/` is git-ignored and nothing in it is committed. Several MCP tools filter on `now()`
against a seed with absolute dates, so a set replays only on the day it was recorded. T-P-106
(a fixed clock) removes that limit; until then, record and replay on the same day, and
`e2e-live-replay` runs only when started by hand.

| File | Purpose |
|------|---------|
| `recordings/*.json` | Git-ignored. Fixtures, keyed by a hash of the normalised request (model, system, messages, tools). The n-th identical request in a run is `<key>.<n>.json` (the first is `<key>.json`), so replay serves repeated requests, such as each session's opening brief, in recorded order |
| `recordings/misses/` | Written by replay: the normalised request for each miss, to diff against the nearest recording |
| `compose.yaml` | Overlay on `docker-compose.yaml`: sets `LLM_FIXTURE_DIR=/app/llm-fixtures` and `LLM_FIXTURE_ALLOW=1` and bind-mounts `recordings/` there |
| `run-live-e2e` | `record` or `replay`: fresh stack, then the live specs, then `scripts/demo all --check` |

## What runs

`run-live-e2e` starts the stack as its own compose project, `lms-llm-fixtures`, so it gets
fresh volumes: a freshly seeded database (`--seed 42`) every time. Then, in this order:

1. `E2E_LIVE=1 pnpm exec playwright test login.live scenario-` in `src/frontend`: the Chat UI
   specs for scenarios 1, 3, 10 and 11 sign in with the real `login(page, username)` fixture and
   drive the real orchestrator. Each takes its user, course and message from
   `src/platform/scenarios/<id>-*.yaml`, approves every approval gate the YAML scripts, and
   mirrors the YAML's `xfail`.
2. `uv run python src/platform/scripts/demo all --check`.

A fixture matches only a request made against the same database state, so replay must repeat the
recording run: same order, same fresh seed. Both modes go through this one script for that
reason. Playwright runs live specs on one worker, in file order.

## Replay

```bash
# The demo stack owns the lms-* container names, so stop it first. Never add -v: that deletes
# the demo database.
docker compose down
set -a; . ./.env; set +a
src/platform/llm-fixtures/run-live-e2e replay
docker compose up -d   # the demo stack again, with its database untouched
```

A request with no fixture fails the turn with `LLMFixtureMissError` in the orchestrator log
(`No recorded LLM response for request …`). Re-record.

A replay on a later day than its recording misses; record again rather than debugging the miss.

## Record

Recording makes real model calls, so record only when you are about to replay the same day.
Recording first deletes the existing fixtures, so none outlive the requests they matched.

From GitHub: run the **Record LLM Fixtures** workflow (`.github/workflows/record-llm-fixtures.yaml`,
needs the `ANTHROPIC_API_KEY` repo secret). The same day, run the **CI** workflow by hand with
that run's id as `fixtures_run_id`; `e2e-live-replay` downloads its `llm-fixtures` artifact into
`recordings/` and replays it.

Locally:

```bash
docker compose down            # never -v
set -a; . ./.env; set +a       # SEED_DEMO_PASSWORD and ANTHROPIC_API_KEY
src/platform/llm-fixtures/run-live-e2e record
src/platform/llm-fixtures/run-live-e2e replay   # same day: confirm the set replays cleanly
docker compose up -d
```

Once T-P-106 lands: commit `recordings/` (drop it from `.gitignore`), run `e2e-live-replay` on
push and PR again, and, once T-E-134 makes the scenarios green, remove its
`continue-on-error: true`.

`KEEP_STACK=1` leaves the `lms-llm-fixtures` stack running for debugging. Stop it with
`docker compose -p lms-llm-fixtures -f docker-compose.yaml -f src/platform/llm-fixtures/compose.yaml down -v`
(it removes only that project's volumes).
