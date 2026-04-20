# CLAUDE.md — Data & MCP worktree

You are the Data & MCP agent. Your workstream is defined in SPEC.md §10 "Workstream 3 — Data & MCP". You own `src/data-mcp/` and nothing else.

## Your mission

1. Build the database schema per `contracts/db-schema.sql`. Alembic migrations must produce exactly that schema.
2. Build the deterministic seed script producing the CS 101 dataset (SPEC.md §3.4).
3. Build the graph library (`graph_lib/`) with the functions other workstreams depend on.
4. Build the seven MCP servers (SPEC.md §6).
5. Write contract tests for every MCP tool.

## Your rules

Same as Engine. Key points for you:

- **`contracts/db-schema.sql` is law.** Your Alembic migrations must produce it exactly. CI verifies.
- Every MCP tool in `contracts/mcp-tools.md` must have a contract test.
- MCP servers are separate processes; each in its own subdirectory.
- Stay in `src/data-mcp/**`.

## Your loop

Standard ralph-wiggum loop, scoped to tasks tagged `T-D-*`. See `src/engine/CLAUDE.md` for the loop template.

## Where to start

Read in this order:
1. `SPEC.md` — §1, §2, §3, §6, §8, §10, §11, §14
2. `contracts/db-schema.sql` — the authoritative schema
3. `contracts/mcp-tools.md` — authoritative tool signatures
4. `contracts/agent-manifests.yaml` — to understand which tools each agent depends on

Your first claim is `T-D-001 — Postgres container + connection helper`. Then `T-D-002 — Learning graph schema migration`. Those two unblock the rest.

## Layout

```
src/data-mcp/
├── schema/                      # Pydantic models + SQLAlchemy ORM if needed
├── migrations/                  # Alembic (match contracts/db-schema.sql exactly)
├── graph_lib/                   # Shared library imported by MCP servers
│   ├── neighbors.py
│   ├── subgraph.py
│   ├── path_to_mastery.py
│   ├── evidence_summary.py
│   └── aggregate.py
├── seed/
│   └── cs101.py                 # deterministic seed script
├── mcp_servers/
│   ├── content/
│   ├── roster/
│   ├── assessments/
│   ├── analytics/
│   ├── sis/
│   ├── communications/
│   └── standards/
└── tests/
    └── contract/                # contract tests per server
```

## Graph library discipline

The graph library is the most load-bearing shared code in the repo. Other workstreams depend on its functions being correct and fast.

- `neighbors(node_id, edge_kind=None, direction='both', depth=1)` — returns related nodes
- `subgraph(root_ids, max_depth)` — returns a bounded subgraph
- `path_to_mastery(person_id, node_id)` — returns the graph path from current mastery to target
- `evidence_summary(person_id, node_ids)` — aggregated mastery evidence
- `aggregate(scope, metric, window)` — aggregated analytics over the graph

Each of these has a canonical test suite. They must be correct before higher-level MCP tools can rely on them.

## Seed script determinism

The seed is deterministic from a fixed random seed. Running `uv run python -m src.data_mcp.seed.cs101 --seed 42` on two fresh databases MUST produce byte-identical state. This matters because scenario tests rely on specific student IDs, evidence patterns, and analytics shapes.

## MCP server template

Each MCP server is a Python process using the official `mcp` SDK. Minimum template:

```python
from mcp import Server, Tool
from mcp.types import TextContent
from .tools import list_tools, call_tool

async def main():
    server = Server("content")
    @server.list_tools()
    async def _list() -> list[Tool]:
        return list_tools()
    @server.call_tool()
    async def _call(name, args):
        return await call_tool(name, args)
    await server.run_stdio()
```

Tools return JSON-serializable dicts. Every tool emits a structured log record (fields: `tool`, `args_digest`, `latency_ms`, `success`, `error`).

## Hard constraints

- No schema drift. Alembic migrations + `contracts/db-schema.sql` + live DB state must all agree.
- No tool surface area that isn't in `contracts/mcp-tools.md`. If an agent needs a new tool, the tool must be added to the contract first (T-C task).
- No N+1 queries in hot paths (analytics, graph traversal). Use SQL or bulk ops.
- No direct SQL injection risk. Parameterize everything.
- No cross-persona data leaks. If the orchestrator's guardrail fails, we still want defense in depth — each tool that returns person-specific data MUST accept and check a `requesting_person_id` against `persona_scope`.
