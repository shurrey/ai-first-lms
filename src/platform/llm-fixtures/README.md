# Recorded LLM fixtures

`recordings/` holds the orchestrator's recorded Anthropic responses, one JSON file per request
(engine side: `src/engine/llm_fixture.py`). With them, the full stack runs the live Chat UI
scenario specs and `scripts/demo all --check` with no API key and no model cost. CI's
`e2e-live-replay` job (`.github/workflows/ci.yaml`) does exactly that on every push and PR, from
the committed `recordings/`.

Several tools filter on "now" (upcoming assignments, evidence
windows, "this month") against a seed with absolute dates, so the overlay pins the clock:
`LMS_AS_OF` (default `2026-10-15`) is set for the seed, every MCP server and the orchestrator,
which use it in place of the real time. A set therefore replays on any day, as long as replay
uses the `LMS_AS_OF` it was recorded with; `run-live-e2e` exports the same default.

| File | Purpose |
|------|---------|
| `recordings/*.json` | Committed. Fixtures, keyed by a hash of the normalised request (model, system, messages, tools). The n-th identical request in a run is `<key>.<n>.json` (the first is `<key>.json`), so replay serves repeated requests, such as each session's opening brief, in recorded order. A request its caller cancelled while recording (the agent backstop: the rest of the turn's wall-time budget) is saved with `"cancelled": true` and no response; replay never answers it, so the same timeout fires again |
| `recordings/misses/` | Git-ignored (`.gitignore` here). Written by replay: the normalised request for each miss, to diff against the nearest recording |
| `compose.yaml` | Overlay on `docker-compose.yaml`: sets `LLM_FIXTURE_DIR=/app/llm-fixtures` and `LLM_FIXTURE_ALLOW=1`, bind-mounts `recordings/` there, sets `LMS_AS_OF` on the seed, MCP servers and orchestrator, and fixes `PII_PSEUDONYM_SALT` (learner pseudonyms in tool results are part of each request key; an unset salt is random per process) |
| `run-live-e2e` | `record`, `replay` or `fill`: fresh stack, then the live specs, then `scripts/demo all --check` |

## What runs

`run-live-e2e` starts the stack as its own compose project, `lms-llm-fixtures`, so it gets
fresh volumes: a freshly seeded database (`--seed 42`) every time. Then, in this order:

1. `E2E_LIVE=1 pnpm exec playwright test login.live scenario-` in `src/frontend`: the Chat UI
   specs for scenarios 1, 3, 10 and 11 sign in with the real `login(page, username)` fixture and
   drive the real orchestrator. Each takes its user, course, message and time cap from
   `src/platform/scenarios/<id>-*.yaml`, approves every approval gate the YAML scripts,
   mirrors the YAML's `xfail`, and fails on a clarifying question. The cap is checked the way
   `scripts/demo` checks it: send to answer, minus time spent at approval gates.
2. `uv run python src/platform/scripts/demo all --check`.

A fixture matches only a request made against the same database state, so replay must repeat the
recording run: same order, same fresh seed. Both modes go through this one script for that
reason. Playwright runs live specs on one worker, in file order.

Scenarios are not independent. The interpreter's prompt carries the person's recent turns in the
course across sessions, so every Dr. Torres CS 101 scenario sees the turns of the ones before it
(UI specs first, then `scripts/demo`). A changed outcome in one scenario therefore changes the
classifier request of every later one in that course.

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

A miss after a prompt, manifest, tool schema, seed or scenario change is expected: record
again. A miss with none of those changed points at a request field that varies between runs;
diff `recordings/misses/<key>.json` against the nearest recording to find it.

## Record

Recording makes real model calls. It first deletes the existing fixtures, so none outlive
the requests they matched. Commit the new set as a whole, once it replays green.

From GitHub: run the **Record LLM Fixtures** workflow (`.github/workflows/record-llm-fixtures.yaml`,
needs the `ANTHROPIC_API_KEY` repo secret), download its `llm-fixtures` artifact into
`recordings/` in place of the existing `*.json`, replay it locally, and commit it.

Locally (then commit the new set as a whole, replacing the old one):

```bash
docker compose down            # never -v
set -a; . ./.env; set +a       # SEED_DEMO_PASSWORD and ANTHROPIC_API_KEY
src/platform/llm-fixtures/run-live-e2e record
src/platform/llm-fixtures/run-live-e2e replay   # confirm the set replays cleanly
docker compose up -d
```

A cancelled request costs its caller's full timeout in replay too. Under the overlay's 600 s
turn budget that can be minutes, and a turn that ends later than it did while recording changes
the history of later turns in the same course, so their requests miss.

`run-live-e2e fill` replays the existing set and calls the API only for requests it has no
fixture for, saving those (`LLM_FIXTURE_FILL_MAX` caps how many). Use it after a change that
alters a few requests late in the run; a prompt, manifest or tool-schema change, or a changed
outcome early in a course's chain of scenarios, alters most keys, so record instead.

`KEEP_STACK=1` leaves the `lms-llm-fixtures` stack running for debugging. Stop it with
`docker compose -p lms-llm-fixtures -f docker-compose.yaml -f src/platform/llm-fixtures/compose.yaml down -v`
(it removes only that project's volumes).
