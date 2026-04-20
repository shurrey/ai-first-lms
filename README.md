# AI-First LMS — Prototype

**Strategic frame (Position C):** Engine-first architecture for AI-native teaching and learning, deployed first inside an LMS-shaped wrapper to meet institutions where they are. The engine serves both shapes.

**North-star test:** For every decision, ask *does this serve the AI-native future, or does it trap us in the LMS past?* When in doubt, choose the answer that keeps the engine portable.

**What this prototype proves:** An LLM-powered orchestrator, given a manifest of ten specialized sub-agents and MCP-backed data access, can produce useful learning outcomes across eleven real use cases. Nothing else is in scope.

---

## Start here

1. Read `SPEC.md` — the master spec. Everything else is detail supporting it.
2. Read `CLAUDE_CODE_SETUP.md` — how to run five concurrent Claude Code agents in worktrees.
3. Read `TASKS.md` — the master task list and the claim protocol that keeps agents from duplicating work.
4. If you are a Claude Code agent assigned to a workstream, read the corresponding file in `worktree-seeds/` — that becomes your worktree's `CLAUDE.md`.
5. Never edit anything in `contracts/` without a human-approved contract-change task.

## Repo layout (the physical shape the agents build into)

```
/
├── SPEC.md                          # Master spec (read this first)
├── CLAUDE_CODE_SETUP.md             # How to run 5 concurrent CC agents
├── TASKS.md                         # Master task list + claim protocol
├── README.md                        # This file
├── contracts/                       # IMMUTABLE cross-workstream interfaces
│   ├── api.openapi.yaml             # HTTP API the frontend consumes
│   ├── events.md                    # SSE event envelope schema
│   ├── agent-manifests.yaml         # All 10 agent manifests
│   └── db-schema.sql                # Ground-truth schema
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
└── src/                             # (Created during build)
    ├── engine/                      # Workstream 1
    ├── agents/                      # Workstream 2
    ├── data-mcp/                    # Workstream 3
    ├── frontend/                    # Workstream 4
    └── platform/                    # Workstream 5
```

## The five workstreams at a glance

| # | Workstream | Owns | Depends on (contracts) |
|---|------------|------|------------------------|
| 1 | Engine | Orchestrator, planning loop, guardrails, streaming | All manifests, events |
| 2 | Agents | 10 sub-agent implementations + prompts | Manifests, MCP tool signatures |
| 3 | Data & MCP | Postgres schema, seed data, 7 MCP servers | db-schema.sql, MCP tool signatures |
| 4 | Frontend | Next.js UI, canvas, activity panel, streaming | api.openapi.yaml, events.md |
| 5 | Platform | Docker Compose, CI, observability, demo runner | Everything |

Workstreams do not share source files. They share contracts.
