# AI-First LMS Prototype — Documentation

## Table of Contents

- [Setup Guide](./setup.md) — How to install, configure, and run the system
- [Architecture](./architecture.md) — System design, data flow, and technology stack
- [Features](./features.md) — Complete feature breakdown for both UIs
- [Learning Science](./learning-science.md) — Pedagogical foundations and how they're implemented
- [API Reference](./api-reference.md) — All orchestrator endpoints
- [Agent Reference](./agents.md) — All 11 agents and their capabilities
- [MCP Server Reference](./mcp-servers.md) — All 7 data servers and their tools
- [Database Schema](./schema.md) — All 25 tables and their relationships

## Phase −1 complete (spec.md §3A)

Phase −1 stabilised the repo before the Round 2 features. The root `CLAUDE.md` is now a repo-level guide, and `SPEC.md` was renamed `SPEC-v1.md` alongside the Round 2 `spec.md`. The SQL injections in `content` and `analytics` are fixed, hostile-input contract tests cover them, and `ruff` S608 guards `mcp_servers/`. Outbound TLS verifies through `truststore` (`src/common/http.py`): there is no `verify=False` in `src/`, and the Python images can bake in a corporate root CA (`CORPORATE_CA_PATH`) and install the exact versions in `uv.lock`. The brief `NameError` and the Ultra student course page are fixed, each with a regression test. Guardrails are wired into the live path: a permission and PII pass in dispatch, `<user_content>` wrapping of tool results, a per-turn `BudgetTracker`, JSON logs and OpenTelemetry traces to Tempo. CI runs from `.github/workflows/`. The task board holds only real work. `contracts/` matches the code, and `check_contracts.py` passes. Making CI a required check on `main` is a GitHub setting a repo admin applies ([setup.md](./setup.md#make-ci-a-required-check-on-main)).
