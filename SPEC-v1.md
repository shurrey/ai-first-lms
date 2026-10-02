# SPEC.md — AI-First LMS Prototype

**Version:** 1.0
**Status:** Approved for build
**Strategic frame:** Position C (engine-first, LMS-shaped deployment first)
**Timeline:** 6 weeks
**Build model:** 5 concurrent Claude Code agents in git worktrees, ralph-wiggum loops, contracts-first coordination

---

## Table of Contents

1. [Strategic Intent and North-Star Test](#1-strategic-intent-and-north-star-test)
2. [System Architecture](#2-system-architecture)
3. [Data Model: The Learning Graph](#3-data-model-the-learning-graph)
4. [The Orchestrator](#4-the-orchestrator)
5. [The Ten Sub-Agents](#5-the-ten-sub-agents)
6. [MCP Servers](#6-mcp-servers)
7. [Frontend](#7-frontend)
8. [Contracts (Source of Truth)](#8-contracts-source-of-truth)
9. [Scenarios (The 11 Demos)](#9-scenarios-the-11-demos)
10. [Workstream Decomposition](#10-workstream-decomposition)
11. [Coordination Protocol](#11-coordination-protocol)
12. [Tech Stack](#12-tech-stack)
13. [Testing Strategy](#13-testing-strategy)
14. [Security and Guardrails](#14-security-and-guardrails)
15. [Demo and Evaluation](#15-demo-and-evaluation)
16. [Exit Criteria](#16-exit-criteria)
17. [Global Conventions](#17-global-conventions)

---

## 1. Strategic Intent and North-Star Test

We are building the engine for AI-native teaching and learning. The first deployment it takes is LMS-shaped because that is where institutional revenue lives in 2026. The engine is not an LMS; it is a set of specialized learning agents orchestrated behind a single entry point, operating over a portable learning graph.

**North-star test.** Any architectural decision that cannot be answered "yes" to this question must be revised: *will this decision survive when the chassis is no longer LMS-shaped?*

Practically this means:

- The data model is a learning graph. Courses, assignments, and gradebook entries are projections over the graph, not the ground truth.
- The orchestrator reasons over agent manifests, not over LMS-specific APIs.
- The frontend is deployment-shaped; the engine is not.
- Compliance, accreditation, and SIS integration are deployment concerns — none of them appear in the engine core.

---

## 2. System Architecture

### 2.1 Component diagram

```
┌────────────────────────────────────────────────────────────────┐
│  Browser (Next.js SPA)                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Context pane │  │ Chat pane    │  │ Activity + canvas    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         └──────────┬──────┘                     │              │
└────────────────────│─────────────────────────────│─────────────┘
                     │ HTTPS POST /api/converse    │ SSE /api/stream
                     ▼                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Orchestrator (FastAPI + LangGraph)                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ Interpret│→ │ Clarify  │→ │ Plan     │→ │ Dispatch     │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────┬───────┘   │
│                                                    │           │
│  Guardrails: permissions · PII filter · write-gate · budget    │
└────────────────────────────────────────────────────│───────────┘
                                                     ▼
            ┌────────────────────────────────────────────────────┐
            │  Sub-agents (Claude Agent SDK, one per agent)       │
            │  Tutor · Course Arch · Content Gen · Assessment     │
            │  Grading · Early Alert · Advising · Accessibility   │
            │  Engagement Analyst · Communication                  │
            └────────────────────────┬────────────────────────────┘
                                     │ MCP (stdio / http)
                                     ▼
            ┌────────────────────────────────────────────────────┐
            │  MCP servers (Python, official SDK)                 │
            │  content · roster · assessments · analytics         │
            │  sis · communications · standards                   │
            └────────────────────────┬────────────────────────────┘
                                     │ asyncpg
                                     ▼
            ┌────────────────────────────────────────────────────┐
            │  Postgres 16 + pgvector                             │
            │  (Learning graph + LMS projections + seed data)     │
            └────────────────────────────────────────────────────┘
```

### 2.2 Request lifecycle

1. User message lands at `POST /api/converse` with session context.
2. Orchestrator opens an SSE stream, begins emitting reasoning events.
3. Interpret step produces a structured intent.
4. If ambiguous, orchestrator emits a `clarify` event and suspends until the UI replies.
5. Plan step produces either a single-agent action or a multi-step DAG.
6. Dispatch invokes the sub-agent(s). Each sub-agent streams tokens back to the orchestrator, which forwards structured events to the UI.
7. Sub-agents invoke MCP tools as needed. Every MCP call is logged.
8. When a sub-agent completes, the orchestrator either synthesizes and finalizes, or advances the plan.
9. Any action requiring human approval emits an `approval_request` event; the UI renders a canvas item with approve/edit/reject; the user's response resumes the flow.
10. Final result includes both the narrative answer and any structured artifacts.

### 2.3 Hard architectural constraints

- The frontend calls only the orchestrator. Full stop.
- Sub-agents do not call other sub-agents. The orchestrator is the only composer.
- Sub-agents do not touch the database. They invoke MCP tools.
- Every state-mutating MCP tool requires human approval to commit.
- Every reasoning step, tool call, and decision is logged with structured metadata.

---

## 3. Data Model: The Learning Graph

The learning graph is the ground truth. LMS abstractions are **projections** over it.

### 3.1 Core entities

**Node (learning unit).** A discrete thing a learner can understand, do, or produce.
```
id            uuid PRIMARY KEY
kind          enum(concept, skill, artifact, assessment_item, resource, outcome)
title         text
description   text
tags          text[]
embedding     vector(1536)       -- pgvector, for semantic search
metadata      jsonb
created_at    timestamptz
```

**Edge (relationship).** Typed relationship between nodes.
```
id            uuid PRIMARY KEY
from_node     uuid → nodes(id)
to_node       uuid → nodes(id)
kind          enum(prerequisite_of, part_of, evidence_of, aligned_with, variant_of)
weight        float
metadata      jsonb
```

**Person.** A human in the system (student, faculty, advisor, admin).
```
id            uuid PRIMARY KEY
roles         text[]              -- ['student', 'faculty', etc.]
display_name  text
email         text
attributes    jsonb               -- demographics, preferences (scoped)
```

**Evidence.** Any observation about a person's relationship to a node.
```
id            uuid PRIMARY KEY
person_id     uuid → persons(id)
node_id       uuid → nodes(id)
kind          enum(attempt, completion, mastery_check, artifact_submission, dialogue_turn)
score         float               -- nullable; continuous or normalized
confidence    float               -- system's confidence in the evidence
source        text                -- which agent/tool produced it
observed_at   timestamptz
payload       jsonb
```

**Attestation.** A durable claim about a person's mastery of a node or set of nodes.
```
id            uuid PRIMARY KEY
person_id     uuid → persons(id)
node_id       uuid → nodes(id)   -- nullable if set-based
node_set      uuid[]              -- for composite attestations
issuer        uuid → persons(id)  -- who issued it (faculty, system)
level         enum(emerging, proficient, mastery)
issued_at     timestamptz
payload       jsonb
```

### 3.2 LMS projections (views over the graph)

These are either materialized views or plain views; all reads go through them, all writes go to the underlying graph tables.

- **courses.** A named subgraph (by tag or collection node).
- **modules.** Subgraphs under a course, typically by `part_of` edges.
- **assignments.** `assessment_item` nodes associated with a course, bound to a due date via `assignment_schedule`.
- **submissions.** `artifact_submission` evidence records.
- **gradebook.** Aggregation of evidence and attestations, projected per course × student.
- **roster.** Persons enrolled in a course (bridging table `enrollments`).

### 3.3 Why this matters for the prototype

Every scenario in this spec can be implemented against this model without touching an "LMS-native" table. The `courses`, `assignments`, and `gradebook` views are the shape faculty expect to see in the UI. But underneath, everything is graph nodes, edges, evidence, and attestations. When we want to ship an AI-native deployment later, we drop the projections and expose the graph directly. The engine does not change.

### 3.4 Seed dataset

**Course:** CS 101 — Introduction to Computer Science, 15-week semester, Fall 2026.
**Students:** 50 synthetic students with realistic distributions (major, GPA, class year, work status, accommodations).
**Faculty:** 1 full-time (Dr. Torres), 1 adjunct (Prof. Lee).
**Advisor:** 1 (Ms. Okafor).
**Modules:** 12 (variables, control flow, functions, data structures, recursion, OOP, file I/O, testing, debugging, algorithms basics, ethics, final project).
**Assignments:** 4 graded (2 code, 1 essay, 1 project), 2 quizzes, 1 discussion forum.
**Graph:** 200 concept nodes, 80 skill nodes, 30 assessment items, ~500 prerequisite edges.
**Events:** 30 days of simulated engagement (page views, video watch %, submission attempts, tutor conversations).

Seed script must be deterministic from a fixed random seed.

---

## 4. The Orchestrator

### 4.1 Responsibilities

1. **Interpret** user message against session context.
2. **Clarify** when intent is ambiguous.
3. **Plan** — produce a DAG of sub-agent invocations.
4. **Dispatch** — execute the plan, streaming progress.
5. **Synthesize** — combine sub-agent outputs into final response.
6. **Enforce guardrails** — permissions, PII, write-gates, budgets.
7. **Log everything** — structured, queryable, replayable.

### 4.2 Internal state (LangGraph)

```python
class OrchestratorState(TypedDict):
    session_id: str
    persona: PersonaContext         # who is asking, what they can do
    conversation: list[Turn]         # prior turns
    current_message: str
    interpretation: Intent | None
    clarification: str | None
    plan: Plan | None
    plan_cursor: int                 # which step we're on
    agent_results: list[AgentResult]
    pending_approvals: list[ApprovalRequest]
    final_answer: FinalAnswer | None
    cost_usd: float                  # running tally
    tokens: int                      # running tally
    budget_exceeded: bool
```

### 4.3 Planning strategies

**ReAct (single-agent, iterative).** Used when the interpretation maps to one agent. The orchestrator lets the sub-agent drive its own tool-use loop and returns.

**Plan-then-execute (multi-agent).** Used when the interpretation requires more than one agent or when the output of one agent feeds the input of another. The orchestrator produces a full plan, shows it to the user for sanity-check (in the activity panel), then executes step-by-step.

Selection is made by a lightweight LLM classifier in the Interpret step; manifests include `composable_with` hints.

### 4.4 Streaming event envelope

All events to the UI use this envelope. See `contracts/events.md` for full schema.

```json
{
  "event": "reasoning" | "plan" | "agent_start" | "agent_token" | "agent_tool_call"
         | "agent_result" | "clarify" | "approval_request" | "final" | "error",
  "session_id": "...",
  "turn_id": "...",
  "sequence": 1234,
  "timestamp": "...",
  "payload": { ... }
}
```

### 4.5 Budget and safety caps

Per-turn hard limits (configurable, but default):
- Max sub-agent invocations: 8
- Max tokens: 250,000
- Max wall time: 120 seconds
- Max MCP tool calls: 40

Exceeding any cap returns an `error` event and halts the turn.

---

## 5. The Ten Sub-Agents

Each agent is defined by (a) a system prompt file, (b) a manifest, (c) a set of permitted MCP tools. Implementation in `src/agents/<name>/`.

### 5.1 Tutor Agent *(student-facing)*
**Purpose:** Socratic tutoring over course content, with an expanded study-companion surface.
**Capabilities:** Concept explanation; worked examples; Socratic dialogue; adaptive quizzing ("quiz me on X"); identification of weak spots from recent evidence; practice-problem generation (via Content Generator invocation by the orchestrator).
**MCP tools:** `content.retrieve`, `content.search`, `roster.get_student_context`, `assessments.list_recent_evidence`, `graph.neighbors`, `graph.path_to_mastery`.
**Never:** Gives answers to open assignments; makes summative judgments.
**Composable_with:** Content Generator (practice problems), Assessment (adaptive quiz items).

### 5.2 Course Architect Agent *(faculty/ID-facing)*
**Purpose:** Draft course structures — outcomes, modules, alignment to standards.
**Capabilities:** Outcome drafting with Bloom's levels; module outline; standards alignment; syllabus draft; identifying gaps between outcomes and assessments.
**MCP tools:** `standards.lookup`, `content.library_search`, `graph.subgraph_for_outcomes`, `content.save_draft`.
**Never:** Finalizes a course; commits changes without faculty approval.

### 5.3 Content Generator Agent *(dual-use: faculty and students)*
**Purpose:** Generate learning materials — summaries, worked examples, study guides, reading guides, slide drafts, practice problems.
**Capabilities:** Given a node or subgraph, produce material in any of the above formats; grounded in source content via retrieval; citation-first; reading-level adaptable.
**Serves:** Faculty ("make a study guide on Chapter 5"); students ("summarize this reading for me"); orchestrator ("generate practice problems for Tutor").
**MCP tools:** `content.retrieve`, `content.search`, `content.save_draft`, `standards.lookup`, `graph.subgraph`.
**Never:** Fabricates citations.

### 5.4 Assessment Agent *(faculty/ID-facing)*
**Purpose:** Generate and validate assessments — quizzes, rubrics, question banks.
**Capabilities:** Question generation across types (MCQ, short answer, essay, code); distractor generation; Bloom's mapping; difficulty estimation; rubric drafting; item analysis warnings; alignment to outcomes.
**MCP tools:** `questions.search_bank`, `questions.create`, `standards.lookup`, `content.retrieve`, `graph.node_for_outcome`.

### 5.5 Grading Assistant Agent *(faculty-facing)*
**Purpose:** Score submissions against a rubric and draft feedback. **Always** drafts, never commits.
**Capabilities:** Per-criterion scoring; per-criterion feedback; holistic feedback; inconsistency/integrity flags for human review; tone normalization.
**MCP tools:** `submissions.get`, `rubrics.get`, `grades.draft`, `grades.commit` *(requires approval gate)*.
**Human approval:** Required for every commit. Flags do not trigger any autonomous action.

### 5.6 Early Alert Agent *(faculty/advisor-facing)*
**Purpose:** Detect at-risk students with explanations; recommend interventions.
**Capabilities:** Multi-signal risk scoring (engagement, performance, attendance, dialogue); per-student explanation; intervention suggestions drawn from institution playbook; small-N guardrails.
**MCP tools:** `analytics.query`, `roster.get`, `interventions.playbook`, `graph.evidence_summary`.
**Never:** Acts without approval; reduces students to single risk scores without explanation.

### 5.7 Advising Agent *(student/advisor-facing)*
**Purpose:** Academic planning — degree audit, course selection, prerequisites, pathway mapping.
**Capabilities:** Degree audit snapshot; next-term recommendations with trade-offs; prerequisite checking; alternative pathways; time-to-graduation projections.
**MCP tools:** `sis.get_transcript`, `sis.degree_audit`, `sis.check_prerequisites`, `catalog.search`, `schedule.availability`.
**In AI-native deployment:** Becomes "Learning Path Navigator" with the same tools, shifting from course-based to competency-based recommendations.

### 5.8 Accessibility Agent *(faculty/ID/student-facing)*
**Purpose:** Accessibility compliance and content adaptation.
**Capabilities:** WCAG 2.1 AA scanning with specific-criterion reports; alt-text generation; caption/transcript generation; readability simplification; translation.
**MCP tools:** `content.retrieve`, `content.save_draft`, `media.process`, `translation.translate`, `compliance.check_wcag`.
**Never:** Silently modifies content; proposes and lets humans accept.

### 5.9 Engagement Analyst Agent *(faculty/admin/advisor-facing)*
**Purpose:** Answer NL questions over learning analytics; produce charts and narratives.
**Capabilities:** Question decomposition; SQL/analytics generation; chart selection; narrative synthesis with caveats; small-sample warnings; correlation-vs-causation discipline.
**MCP tools:** `analytics.query`, `analytics.describe_schema`, `charts.render`, `graph.aggregate`.
**Never:** Over-interprets; hides methodology.

### 5.10 Communication Agent *(faculty/advisor/admin-facing; also serves other agents)*
**Purpose:** Draft and send messages; final recipient-facing communication layer.
**Capabilities:** Audience targeting; tone adjustment; personalization at scale; channel selection (LMS announcement, inbox, email); preview and approval gate.
**MCP tools:** `roster.get`, `messages.draft`, `messages.send` *(requires approval gate)*, `templates.list`.
**Never:** Sends without human confirmation.

---

## 6. MCP Servers

Seven servers. Each is a separate process. Each exposes a focused tool surface. Tool signatures are in `contracts/agent-manifests.yaml`.

| Server | Port (conventional) | Owns | Key tools |
|--------|---------------------|------|-----------|
| `content` | 7001 | Course content, materials, drafts | `retrieve`, `search`, `save_draft`, `library_search`, `list_modules` |
| `roster` | 7002 | Persons, sections, enrollments | `get`, `get_student`, `get_student_context`, `list_by_course` |
| `assessments` | 7003 | Questions, submissions, rubrics, grades | `create_question`, `search_bank`, `get_submission`, `get_rubric`, `draft_grade`, `commit_grade`, `list_recent_evidence` |
| `analytics` | 7004 | Events, metrics, queries | `query`, `describe_schema`, `trend`, `cohort_compare`, `render_chart` |
| `sis` | 7005 | Transcripts, degree audits, catalog | `get_transcript`, `degree_audit`, `check_prerequisites`, `catalog_search`, `schedule_availability` |
| `communications` | 7006 | Messages, templates | `draft_message`, `send_message`, `list_templates` |
| `standards` | 7007 | Learning standards, WCAG, outcomes | `lookup`, `align`, `check_wcag`, `list_frameworks` |

Plus a shared `graph` library (not a separate server, imported by all MCP servers) exposing `neighbors`, `subgraph`, `path_to_mastery`, `evidence_summary`, `aggregate`, `node_for_outcome`.

All tools return structured JSON. All tools that mutate state emit an outbox event that the orchestrator can observe.

---

## 7. Frontend

### 7.1 Three panels

- **Left — Session context.** Persona switcher (Student / Faculty / Advisor / Admin), course selector, conversation history.
- **Center — Chat.** Streamed user/assistant turns. Markdown rendering. Inline citations.
- **Right — Activity + Canvas.**
  - **Activity (top):** live tree of orchestrator → agent → tool calls, with status and timing.
  - **Canvas (bottom):** structured artifacts. Rubric, quiz, chart, draft email, degree audit. Interactive — approve, edit, reject, comment.

### 7.2 Streaming

SSE from `GET /api/stream?session_id=...&turn_id=...`. Events land in a ringbuffer keyed by `sequence`. UI renders from the ringbuffer so reconnection picks up cleanly.

### 7.3 Approval UX

When the stream emits `approval_request`, the relevant canvas item enters an approval state. The user must explicitly click Approve, Edit (opens inline editor), or Reject. The user's response posts to `POST /api/approval` which the orchestrator receives and continues the plan.

### 7.4 Persona-scoped behavior

The persona selected controls:
- Which agents surface in the suggested-prompt pills
- What data the MCP servers will return (enforced at the orchestrator guardrail, not the UI)
- How the canvas renders (student sees a study guide as a readable document; faculty sees it with editorial controls)

---

## 8. Contracts (Source of Truth)

Everything in `contracts/` is immutable from a workstream's perspective. Any change to a contract file is a cross-workstream event that requires a "contract change" task explicitly approved by a human.

- `contracts/api.openapi.yaml` — the HTTP/SSE API the frontend consumes. Source of truth for workstreams 1 and 4.
- `contracts/events.md` — the SSE event envelope and each event type. Source of truth for workstreams 1 and 4.
- `contracts/agent-manifests.yaml` — all 10 agent manifests. Source of truth for workstreams 1 and 2.
- `contracts/mcp-tools.md` — all MCP tool signatures. Source of truth for workstreams 2 and 3.
- `contracts/db-schema.sql` — the full schema. Source of truth for workstream 3.

A CI job verifies:
- All manifests parse.
- All MCP tool signatures referenced by manifests exist.
- All API endpoints referenced by the frontend are present in the OpenAPI.
- DB migrations match the schema.

---

## 9. Scenarios (The 11 Demos)

Each scenario has: a one-line user prompt, the expected agent plan, the expected canvas artifacts, and a test oracle. Scenarios live in `src/platform/scenarios/` as runnable `.yaml` files; the demo CLI can run any of them end-to-end.

| # | Prompt | Persona | Agents | Canvas |
|---|--------|---------|--------|--------|
| 1 | "Can you help me understand recursion?" | Student | Tutor | Dialogue |
| 2 | "Build me a 10-question quiz on photosynthesis." | Faculty | Assessment (+ Content Gen) | Quiz preview |
| 3 | "Grade submissions for Essay 3 with my rubric." | Faculty | Grading Assistant | Rubric grid, approval gate |
| 4 | "Who in my class is at risk and why?" | Faculty | Early Alert (+ Engagement Analyst) | Ranked list + risk cards |
| 5 | "Draft an announcement about Monday's midterm." | Faculty | Communication | Message preview, approval gate |
| 6 | "Is my Intro to Biology course WCAG compliant?" | Faculty | Accessibility | Compliance report |
| 7 | "What should I take next semester?" | Student | Advising | Degree audit + recommendations |
| 8 | "Help me draft a syllabus for Intro to Data Ethics." | Faculty | Course Architect (+ Content Gen) | Syllabus draft |
| 9 | "Show me engagement trends in CS 101 this month." | Faculty | Engagement Analyst | Charts + narrative |
| 10 | **"For students struggling with Ch 5, make a tailored study guide and send it."** | Faculty | Early Alert → Content Gen → Communication | Multi-step canvas with approvals |
| 11 | **"I want to get better at writing. Help me build a path."** *(AI-native)* | Student | Advising (as Learning Path Navigator) → Tutor | Learning graph view + pathway |

Scenario 10 is the flagship multi-agent demo. Scenario 11 is the AI-native demo that proves the engine works outside the LMS shape.

---

## 10. Workstream Decomposition

Five workstreams, each owned by one Claude Code agent running a ralph-wiggum loop in its own worktree. Paths are disjoint.

### Workstream 1 — Engine

**Owns:** `src/engine/`
**Builds:** Orchestrator service (FastAPI), LangGraph state machine, agent manifest loader, planning logic, guardrails, SSE streaming, approval-flow backend, session store, cost/token accounting.
**Depends on (read-only):** `contracts/agent-manifests.yaml`, `contracts/events.md`, `contracts/api.openapi.yaml`.
**Key deliverables:** `POST /api/converse`, `GET /api/stream`, `POST /api/approval`, state persistence in Postgres, structured logs.

### Workstream 2 — Agents

**Owns:** `src/agents/`
**Builds:** Ten sub-agent implementations using Claude Agent SDK. Each agent is a subdirectory with `system_prompt.md`, `manifest.yaml` (a copy local to the agent that CI verifies matches the contract), `agent.py`, and `tests/`.
**Depends on:** `contracts/agent-manifests.yaml`, `contracts/mcp-tools.md`.
**Key deliverables:** Ten working sub-agent processes, each callable with a structured input and returning structured output; prompt files checked in; per-agent eval harness.

### Workstream 3 — Data & MCP

**Owns:** `src/data-mcp/`
**Builds:** Postgres schema (matches `contracts/db-schema.sql`), Alembic migrations, graph library, seed script (deterministic CS 101), seven MCP servers. Plus pgvector index on node embeddings.
**Depends on:** `contracts/db-schema.sql`, `contracts/mcp-tools.md`.
**Key deliverables:** `docker compose up postgres seed-data mcp-*` brings up a working data layer; all MCP tools respond correctly to canned test cases.

### Workstream 4 — Frontend

**Owns:** `src/frontend/`
**Builds:** Next.js application with the three-panel UI, SSE client, approval UX, canvas renderers for rubric/quiz/chart/message/degree-audit, persona switcher, conversation history.
**Depends on:** `contracts/api.openapi.yaml`, `contracts/events.md`.
**Key deliverables:** A running Next.js app that can be pointed at a live orchestrator and run any of the 11 scenarios.

### Workstream 5 — Platform

**Owns:** `src/platform/`
**Builds:** Root `docker-compose.yaml`, CI workflows, OpenTelemetry instrumentation, Grafana dashboards, `scripts/demo` CLI, scenario runner (the yaml files + the executor), smoke tests, deployment script for the single-VM demo environment.
**Depends on:** All other workstreams (integrates them).
**Key deliverables:** `docker compose up` produces a working system; `scripts/demo 10` runs scenario 10 and reports pass/fail; `scripts/deploy demo` pushes to the demo VM.

### Dependency ordering

Workstream 3 (Data & MCP) has the longest critical path because other workstreams depend on it for local development. Recommended bootstrap order on day 1: Platform (just the compose skeleton) → Data & MCP → Engine → Agents → Frontend. In parallel after day 3, all five workstreams run concurrently.

---

## 11. Coordination Protocol

### 11.1 The problem

Five agents editing the same repo concurrently will collide if (a) they touch the same files, or (b) they pick the same tasks, or (c) they modify shared contracts.

### 11.2 The solution

**Pathwise isolation.** Each workstream owns a top-level path. Agents are forbidden (via CLAUDE.md instruction and git hooks) from editing outside their path, except for:
- `contracts/` — requires a contract-change task
- `tasks/` — requires the claim protocol below

**Contract-first discipline.** Any change to a contract is a cross-workstream event. Contract changes require a human-approved task tagged `contract-change`. The humans are you and/or me during integration.

**Task claim protocol.** The master list lives in `TASKS.md`. Actual task files live in `tasks/open/<task-id>.md`. An agent claims a task like this:

```bash
# in its worktree
git pull origin main
git mv tasks/open/T-042.md tasks/claimed/engine/T-042.md
git add . && git commit -m "claim: T-042"
git push
```

If another agent raced and already claimed it, the push fails (remote has the move already). The agent pulls, picks a different task, tries again.

Completion:

```bash
git mv tasks/claimed/engine/T-042.md tasks/done/T-042.md
# commit and push the actual work alongside
```

Atomicity is provided by git. No external coordination service.

**Conflict zones.**
- `contracts/` — requires human approval (opened as a contract-change task)
- `TASKS.md` — rebuilt from `tasks/*` by a CI job; agents do not edit it directly
- `src/platform/docker-compose.yaml` — owned by Platform; if another workstream needs a service entry, they open a task against Platform

### 11.3 The ralph-wiggum loop (per agent)

```
loop forever:
  git pull origin main
  task = claim_next_task_in_my_workstream()
  if task is None:
    sleep 60s; continue
  
  work_on(task)               # read task spec, implement, write tests
  run_tests_locally()
  if any test fails:
    iterate until green or escalate to human
  
  commit_all_changes("<type>: <task-id> — <summary>")
  push
  move_task_to_done(task)
  commit_and_push
```

The loop is defined explicitly in each workstream's `CLAUDE.md`. Claude Code runs it as a persistent session. See `CLAUDE_CODE_SETUP.md` for how to launch these.

### 11.4 Escalation

An agent escalates to a human (stops the loop and leaves a note) when:
- A task requires a contract change
- Tests fail in a way the agent cannot resolve in 3 iterations
- A dependency on another workstream is blocking
- The task spec is ambiguous

Escalation writes to `tasks/blocked/<task-id>.md` with a human-readable note.

---

## 12. Tech Stack

### 12.1 Languages and runtimes

| Concern | Choice | Why |
|---------|--------|-----|
| Orchestrator, agents, MCP | Python 3.12 | LangGraph and Claude Agent SDK are first-class in Python |
| Frontend | TypeScript 5.4 | Type safety for streaming event handling; Next.js ecosystem |
| Data | PostgreSQL 16 + pgvector | One DB for everything; vector search built in |
| Migrations | Alembic | De-facto standard for Python+Postgres |
| Package management (Python) | `uv` | Much faster than poetry or pip; cleaner lockfiles |
| Package management (JS) | `pnpm` | Workspaces, fast, disk-efficient |

### 12.2 Key libraries

- **Orchestrator:** `fastapi`, `langgraph`, `anthropic`, `sse-starlette`, `asyncpg`, `opentelemetry-api`
- **Agents:** `claude-agent-sdk`, `anthropic`, `pydantic`
- **MCP:** `mcp` (official SDK), `asyncpg`, `pydantic`
- **Frontend:** `next@14`, `react@18`, `tailwindcss`, `shadcn/ui`, `@tanstack/react-query`, `eventsource-parser`, `recharts`
- **Testing:** `pytest`, `pytest-asyncio`, `playwright`, `testcontainers`
- **Observability:** `opentelemetry-sdk`, Grafana Cloud free tier

### 12.3 Models

- **Orchestrator reasoning:** Claude Sonnet 4.6 (`claude-sonnet-4-6`)
- **Sub-agents (default):** Claude Sonnet 4.6
- **Sub-agents (cheap path):** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) for Content Generator, Communication, and Tutor's small-talk. Configurable per agent in manifest.
- **Embeddings:** `voyage-3-large` or `text-embedding-3-large` (decide in Workstream 3 based on pgvector performance; either works)

### 12.4 Directory layout

```
src/
├── engine/
│   ├── api/              # FastAPI routes
│   ├── graph/            # LangGraph state machine
│   ├── manifest/         # Manifest loader
│   ├── guardrails/       # Permission, PII, write-gate, budget
│   ├── streaming/        # SSE helpers
│   └── tests/
├── agents/
│   ├── tutor/
│   │   ├── system_prompt.md
│   │   ├── manifest.yaml
│   │   ├── agent.py
│   │   └── tests/
│   ├── course_architect/
│   ├── content_generator/
│   ├── assessment/
│   ├── grading_assistant/
│   ├── early_alert/
│   ├── advising/
│   ├── accessibility/
│   ├── engagement_analyst/
│   └── communication/
├── data-mcp/
│   ├── schema/
│   ├── migrations/
│   ├── graph_lib/
│   ├── seed/
│   ├── mcp_servers/
│   │   ├── content/
│   │   ├── roster/
│   │   ├── assessments/
│   │   ├── analytics/
│   │   ├── sis/
│   │   ├── communications/
│   │   └── standards/
│   └── tests/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── styles/
│   └── tests/
└── platform/
    ├── docker-compose.yaml
    ├── scripts/
    │   ├── demo               # Demo CLI
    │   ├── deploy
    │   └── seed-demo-env
    ├── scenarios/
    │   ├── 01-tutor.yaml
    │   ├── ...
    │   └── 11-ai-native-path.yaml
    ├── otel/
    ├── ci/
    └── smoke-tests/
```

### 12.5 Deployment shape

**Local (dev and demo):** `docker compose up`. Everything runs on localhost. Frontend at `:3000`, orchestrator at `:8000`, Postgres at `:5432`, MCP servers at `:7001-7007`, Grafana at `:3001`.

**Remote (external evaluators):** Same compose bundle on a single VPS (t3.large equivalent). Caddy for TLS and basic auth. That's it. No Kubernetes, no load balancer, no blue-green. Uptime is best-effort for six weeks.

---

## 13. Testing Strategy

Four levels, all required:

1. **Unit tests** per workstream, ≥70% coverage on non-trivial logic. `pytest` for Python, Vitest for TypeScript.
2. **MCP contract tests.** Each MCP tool has canned input/output cases. These run in CI against a freshly seeded database.
3. **Agent eval harness.** Each sub-agent has ≥5 canned test inputs with expected output shapes and qualitative rubrics. Runs nightly.
4. **Scenario integration tests.** Each of the 11 scenarios has a test fixture. `scripts/demo <id> --check` runs the scenario end-to-end and validates the final state. CI runs these.

CI fails any PR that:
- Fails unit tests in its own workstream
- Breaks any MCP contract test
- Breaks any scenario integration test that was passing before the change
- Changes a contract file without a corresponding approved contract-change task

---

## 14. Security and Guardrails

### 14.1 Permissions

Prototype uses a simple role-based model (not Cedar — Cedar is a product feature, not a prototype need). Every MCP tool has `allowed_roles` metadata. Orchestrator checks the session's persona against the tool's allowed_roles before dispatching. Enforcement is at the orchestrator, not at the MCP server.

### 14.2 PII

Student PII (email, full name, demographics) is stripped from LLM prompts by default. Agents that need specific fields must declare them in their manifest (`requires_pii: [email, name]`) and the orchestrator's guardrail injects only the declared fields.

### 14.3 Write-gates

Any MCP tool tagged `mutates: true` and `requires_approval: true` does not execute on call; it returns a `draft` with a preview, and the orchestrator emits an `approval_request` event. Only after `POST /api/approval` does the orchestrator re-invoke the tool with the approved payload.

### 14.4 Budget

Per-turn and per-session caps. Exceeding a cap halts the turn and emits an `error` event.

### 14.5 Prompt injection

Every text field retrieved from the DB (content, submissions, messages) is wrapped in `<user_content>...</user_content>` delimiters before being passed to an LLM. System prompts explicitly instruct agents to treat wrapped content as data, not instructions. This is belt-and-suspenders — not perfect, but meaningfully raises the bar.

### 14.6 Secrets

No secrets in the repo. `.env.example` checked in; `.env` git-ignored. Agents load via `pydantic-settings`. Anthropic API key is read from env.

---

## 15. Demo and Evaluation

### 15.1 How we demo

Three demo modes, same codebase:

1. **Scripted walkthrough.** `scripts/demo all` runs all 11 scenarios in sequence, recording video of the UI and asserting on the final state. This is the "engineering demo" — proof that it works.
2. **Live demo.** Human operator drives the UI, switching personas, running each scenario with narration. This is the "stakeholder demo."
3. **Unscripted sandbox.** External evaluators log in (demo auth), pick a persona, and do whatever they want. This is the "feedback demo."

### 15.2 External evaluator protocol

Before week 6:
- Recruit 3 faculty (one R1, one community college, one online-first), 2 advisors, 3 students.
- Pre-demo: 20-minute orientation on the sandbox.
- Demo: 45-minute free-form session per evaluator, recorded with consent.
- Post-demo: structured feedback form covering accuracy, usefulness, trust, latency, and open-text for surprises.

### 15.3 Feedback synthesis

All sessions and written feedback land in `docs/feedback/`. At end of week 6 we produce a decision memo: keep / deepen / cut per agent, keep / refactor / replace per technical component, with explicit rationales.

---

## 16. Exit Criteria

The prototype is done when:

**Engineering**
- [ ] All 11 scenarios pass `scripts/demo <id> --check` on a clean `docker compose up`.
- [ ] Scenario 10 (flagship multi-agent) and Scenario 11 (AI-native) both run reliably with approval gates.
- [ ] P95 latency ≤ 8s single-agent, ≤ 20s multi-agent.
- [ ] All MCP contract tests green.
- [ ] All agent eval suites at ≥80% pass rate.
- [ ] Observability dashboard shows per-turn traces.

**User signal**
- [ ] ≥ 6 external evaluators have completed unscripted sessions.
- [ ] Net positive qualitative feedback on ≥ 7 of the 11 scenarios.
- [ ] Documented, actionable feedback per scenario.

**Decision readiness**
- [ ] Decision memo complete: keep/deepen/cut per agent.
- [ ] Technical decision memo: LangGraph, Claude Agent SDK, MCP, Postgres, and Next.js are each either validated or have a documented replacement path.
- [ ] Product decision memo: which scenarios graduate into the production MVP.

---

## 17. Global Conventions

### 17.1 Code style

- **Python:** `ruff` (format + lint), `mypy --strict`, docstrings on all public functions, `from __future__ import annotations`, no `*` imports.
- **TypeScript:** `biome` (format + lint), strict mode on, no `any` without justification in a comment.
- **SQL:** lowercase keywords, snake_case tables and columns, explicit column lists (no `SELECT *` in production code).

### 17.2 Commit messages

Conventional commits. Every commit references a task id.

```
<type>(<scope>): T-<id> <summary>

- <detail bullet>
- <detail bullet>
```

`type`: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `contract`.
`scope`: one of `engine`, `agents`, `data-mcp`, `frontend`, `platform`, `contracts`.

### 17.3 Branching

- `main` is the integration branch. Ralph-wiggum agents push here directly if tests pass. (This is intentional — prototype, not production.)
- Contract changes open PRs that a human reviews.
- Each worktree tracks `main` — there are no per-agent branches in steady state.

### 17.4 Documentation

Every workstream has a `src/<workstream>/README.md` describing:
- What this workstream owns
- How to run it locally
- How tests work
- How to add a new <thing> (agent, MCP tool, scenario, etc.)

### 17.5 Error handling

Never swallow exceptions silently. Every error is logged with structured metadata and either surfaced as an `error` event to the UI or raised into the test harness. Rule of thumb: if the user could reasonably care, the error must reach them.

---

## End of SPEC

The rest of the repo (`TASKS.md`, `CLAUDE_CODE_SETUP.md`, worktree seeds, contracts) is operational detail that makes this spec executable by five concurrent Claude Code agents. Start there if you're a Claude Code agent being onboarded.
