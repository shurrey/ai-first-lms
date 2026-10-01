# AI-First LMS — Prototype

**Strategic frame (Position C):** Engine-first architecture for AI-native teaching and learning, deployed first inside an LMS-shaped wrapper to meet institutions where they are. The engine serves both shapes.

**North-star test:** For every decision, ask *does this serve the AI-native future, or does it trap us in the LMS past?* When in doubt, choose the answer that keeps the engine portable.

**What this prototype proves:** An LLM-powered orchestrator, given a manifest of ten specialized sub-agents and MCP-backed data access, can produce useful learning outcomes across eleven real use cases. Nothing else is in scope.

---

## Start here

1. Read `SPEC-v1.md`, the base architecture spec, then `spec.md`, the Round 2 delta. Where they conflict, `spec.md` wins.
2. Read `CLAUDE.md` for how to run and test the repo.
3. Read `CLAUDE_CODE_SETUP.md` for how to run five concurrent Claude Code agents in worktrees.
4. Read `TASKS.md` for the task file format and the claim protocol that keeps agents from duplicating work.
5. If you are a Claude Code agent assigned to a workstream, read the matching file in `worktree-seeds/`. It is copied into your worktree as its `CLAUDE.md`.
6. Never edit anything in `contracts/` without a human-approved contract-change task.

Run it with `docker compose up -d`. The Chat UI is at http://localhost:3000 and the Ultra UI at http://localhost:3100. See `docs/setup.md`.

## Repo layout

```
/
├── SPEC-v1.md                       # Base architecture spec (formerly SPEC.md)
├── spec.md                          # Round 2 delta; wins on conflict
├── CLAUDE.md                        # Repo-level guide: run, test, contracts
├── CLAUDE_CODE_SETUP.md             # How to run 5 concurrent CC agents
├── TASKS.md                         # Task file format + claim protocol
├── README.md                        # This file
├── docker-compose.yaml              # Full local stack
├── contracts/                       # Cross-workstream interfaces (change only via T-C-*)
│   ├── api.openapi.yaml             # HTTP API the UIs consume
│   ├── events.md                    # SSE event envelope schema
│   ├── agent-manifests.yaml         # Agent manifests
│   ├── mcp-tools.md                 # MCP tool signatures
│   └── db-schema.sql                # Ground-truth schema
├── docs/                            # Architecture, setup, API and agent docs
├── tasks/
│   ├── open/                        # Unclaimed tasks
│   ├── claimed/<worktree-id>/       # In-progress tasks
│   └── done/                        # Completed tasks
├── worktree-seeds/                  # Starter CLAUDE.md for each worktree
│   ├── engine.md
│   ├── agents.md
│   ├── data-mcp.md
│   ├── frontend.md
│   └── platform.md
└── src/
    ├── engine/                      # Workstream 1
    ├── agents/                      # Workstream 2
    ├── data_mcp/                    # Workstream 3
    ├── frontend/                    # Workstream 4: Chat UI (:3000)
    ├── ultra-frontend/              # Workstream 4: Ultra UI (:3100)
    └── platform/                    # Workstream 5
```

## The five workstreams at a glance

| # | Workstream | Owns | Depends on (contracts) |
|---|------------|------|------------------------|
| 1 | Engine | Orchestrator, planning loop, guardrails, streaming | All manifests, events |
| 2 | Agents | Sub-agent prompts, manifests, evals | Manifests, MCP tool signatures |
| 3 | Data & MCP | Postgres schema, seed data, 7 MCP servers | db-schema.sql, MCP tool signatures |
| 4 | Frontend | Both Next.js UIs: canvas, activity panel, streaming | api.openapi.yaml, events.md |
| 5 | Platform | Docker Compose, CI, observability, demo runner | Everything |

Workstreams do not share source files. They share contracts.
