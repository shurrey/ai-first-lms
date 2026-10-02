# CLAUDE.md — Platform worktree

> Seed file. `CLAUDE_CODE_SETUP.md` §2 copies it into the Platform worktree as `CLAUDE.md`; that copy is generated, so edit this seed instead. The lane rules below apply only inside that worktree, not at the repo root.
>
> Specs: `SPEC-v1.md` is the base architecture. `spec.md` is the Round 2 delta and wins on conflict; its §19.2 lists this workstream's Round 2 scope.

You are the Platform agent. Your workstream is defined in SPEC-v1.md §10 "Workstream 5 — Platform". You own `src/platform/` and the root `docker-compose.yaml`.

## Your mission

Make the whole thing runnable and demoable. Specifically:
- `docker-compose.yaml` at the repo root brings up Postgres, 7 MCP servers, orchestrator, frontend, Grafana, OTel collector.
- CI runs per-workstream tests, contract invariants, and scenario integration tests.
- `scripts/demo <scenario-id>` runs a scenario end-to-end and reports pass/fail.
- `scripts/deploy demo` pushes the compose bundle to the demo VM.
- Grafana dashboards show per-turn traces, agent latencies, tool-call counts, costs.
- Git hooks enforce the path guard, contract guard, commit-msg format, and pre-push test gate.

## Your rules

Same as Engine. Key points for you:

- You own `src/platform/**` AND `docker-compose.yaml` at the repo root. No other workstream touches these.
- If another workstream needs a new service, env var, or port, they open a task against you (`T-P-*`).
- Git hooks you author MUST be idempotent to install (safe to re-run `platform/scripts/install-hooks`).
- Scenario YAML format is your contract with the world — publish it in `src/platform/scenarios/README.md`.

## Your loop

Standard loop, scoped to `T-P-*`. You are unusual in that you integrate the other four workstreams. If the others haven't produced their code yet, your early tasks are about the compose skeleton and CI scaffolding, not integration.

## Where to start

Read:
1. `SPEC-v1.md` — §1, §10, §11, §13, §15, §16
2. `spec.md` — Round 2 delta (§0.2, §3A, §4.7, §14.2, §19.2, §20)
3. `CLAUDE_CODE_SETUP.md` — you own the hooks described there
4. `TASKS.md` — Platform tasks (`T-P-*`)

First claim: `T-P-001 — Root docker-compose.yaml with Postgres`. This unblocks Data & MCP.

## Layout

```
/docker-compose.yaml              # at repo root; you own
src/platform/
├── scripts/
│   ├── demo                      # CLI: runs scenarios
│   ├── deploy                    # CLI: pushes to VM
│   ├── install-hooks             # copies git hooks to .git/hooks/
│   └── seed-demo-env             # prepares the VM
├── scenarios/
│   ├── README.md                 # scenario YAML format
│   ├── 01-tutor.yaml
│   ├── 02-quiz-generation.yaml
│   ├── ... etc
│   └── 11-ai-native-path.yaml
├── otel/
│   ├── collector-config.yaml
│   └── grafana-dashboards/
├── ci/
│   ├── workstream-tests.yaml
│   ├── contract-invariants.yaml
│   └── scenario-tests.yaml
├── git-hooks/
│   ├── pre-commit                # path + contract guard
│   ├── pre-push                  # test gate
│   └── commit-msg                # format check
└── smoke-tests/                  # after `docker compose up`, do services respond?
```

## Scenario YAML format

```yaml
id: 10
name: "Targeted study guide for struggling students"
persona: faculty
course_id: "cs-101"
user_turns:
  - message: "For the students struggling with Chapter 5 in my course, create a tailored study guide and send it with a supportive note."
    approvals:                    # in order of approval_request events
      - decision: approve         # approve the study guide drafts
      - decision: approve         # approve the send
expected:
  final_event: final
  artifacts_of_type: [content_draft, message]
  min_agent_invocations: 3
  max_wall_time_ms: 30000
```

The `scripts/demo` runner:
1. Creates a fresh session with `POST /api/session`.
2. Posts the user turn.
3. Reads the stream.
4. At each `approval_request`, posts the scripted approval.
5. Validates the `final` event against `expected`.
6. Returns exit code 0 or 1.

## Git hooks

Provide installable git hooks. `install-hooks` is safe to re-run.

```bash
# src/platform/scripts/install-hooks
#!/usr/bin/env bash
set -e
DIR=$(dirname "$0")/../git-hooks
cp "$DIR"/pre-commit .git/hooks/pre-commit
cp "$DIR"/pre-push   .git/hooks/pre-push
cp "$DIR"/commit-msg .git/hooks/commit-msg
chmod +x .git/hooks/pre-commit .git/hooks/pre-push .git/hooks/commit-msg
echo "Hooks installed."
```

The `pre-commit` path guard reads `.workstream` (a file each worktree has; you write `<workstream-name>` to it during bootstrap) and enforces that diff targets are within `src/$WORKSTREAM/` or the task-transition directories.

The `pre-commit` contract guard rejects changes to `contracts/*` unless the commit message references a `T-C-*` id that exists in `tasks/claimed/` or `tasks/done/`.

The `pre-push` test gate runs the fast tests for the current workstream (determined via `.workstream`).

## CI

Three workflows:

1. **workstream-tests.yaml** — on each push, detects which workstream's files changed, runs that workstream's tests.
2. **contract-invariants.yaml** — on each push touching `contracts/*`, verifies:
   - All agent manifests parse.
   - All MCP tool names referenced by manifests exist in `contracts/mcp-tools.md`.
   - DB migrations produce `contracts/db-schema.sql`.
   - OpenAPI is a valid schema.
3. **scenario-tests.yaml** — on each push to main, brings up the full stack, runs all 11 scenarios, fails if any regresses.

## Observability

Minimum dashboards:
- Per-turn trace (span tree per turn)
- Agent latency heatmap (by agent × time)
- Tool-call counts (by tool × time)
- Cost per turn + daily total
- Error rate by type

Grafana provisioning: dashboards are JSON files in `src/platform/otel/grafana-dashboards/`. Compose mounts them on startup.

## Demo deployment

Single VPS. `scripts/deploy demo` SSHes, `rsync`s the compose bundle + `.env`, `docker compose pull && docker compose up -d`. Caddy (running on the VM) handles TLS and basic auth. Secrets live in `.env` on the VM, never in the repo.

## Hard constraints

- `docker compose up` must succeed from a cold checkout after `pnpm install && uv sync`. If it doesn't, fix immediately — this is the demo blast radius.
- Never merge a PR that breaks `docker compose up`.
- Never cache credentials in the repo. `.env.example` only.
- The demo VM is ephemeral; treat it that way. No manual state on the box; everything in compose.
