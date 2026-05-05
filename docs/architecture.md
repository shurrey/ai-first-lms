# Architecture

## System Overview

The AI-First LMS prototype replaces the traditional LMS paradigm (content delivery + gradebook) with an agent-driven system where AI tutors teach, assess, and adapt to each student. There are no grades — students earn mastery of concepts, which accumulate into microcredentials backed by OpenBadges 3.0.

```
                    +------------------+
                    |   Two Frontends  |
                    | Chat UI (:3000)  |
                    | Ultra UI (:3100) |
                    +--------+---------+
                             |
                         REST/SSE
                             |
                    +--------+---------+
                    |   Orchestrator   |
                    |  (LangGraph +    |
                    |   FastAPI :8000) |
                    +--------+---------+
                             |
                    Claude API (Anthropic)
                             |
              +--------------+--------------+
              |              |              |
        +-----+-----+  +----+----+  +------+------+
        | 11 Agents  |  | Session |  | Lifecycle   |
        | (prompts)  |  | Mgmt    |  | Hooks       |
        +-----+------+  +---------+  +------+------+
              |                              |
         MCP Tool Calls (SSE)         Background Tasks
              |                        (Learning Analyst)
    +---------+---------+
    |   7 MCP Servers   |
    | Content   (:7001) |
    | Roster    (:7002) |
    | Assess    (:7003) |
    | Analytics (:7004) |
    | SIS       (:7005) |
    | Comms     (:7006) |
    | Standards (:7007) |
    +---------+---------+
              |
         +----+----+
         | Postgres |
         | pgvector |
         +----------+
```

## Data Flow

### Student Chat Session

1. **Frontend** sends `POST /api/session` with persona + course
2. **Orchestrator** creates session, persists to DB, generates a page brief in background
3. **Frontend** polls `GET /api/stream` for brief data (SSE)
4. Student types a message → `POST /api/converse`
5. **Orchestrator** loads conversation history from DB
6. **Lifecycle hooks** inject context (retrieval practice on first turn, revision reminders, interleaving)
7. **LangGraph pipeline** runs: Interpret → Plan → Dispatch → Synthesize
8. **Interpret** classifies intent and selects agent(s) via Claude
9. **Dispatch** runs the agent with its allowed MCP tools
10. **Agent** (e.g., Tutor) calls MCP tools, receives data, generates response
11. **MCP guardrails** enforce rules (mastery timing, prerequisite checks)
12. Response streams back via SSE with thinking, tool calls, and final answer
13. Conversation turns persist to `conversation_turns` table
14. **Frontend** auto-refreshes mastery panel after each turn
15. On session end ("bye"), **Learning Analyst** fires as background task

### Mastery Attestation Flow

1. Tutor assesses student understanding during conversation
2. Tutor calls `attestations.attest(person_id, node_id, level)`
3. Runner auto-injects `session_id` into the call
4. **MCP guardrail**: if `level=mastery` and no prior attestation from a different session exists → auto-downgrade to `proficient`
5. If `level=mastery` succeeds → check if all concepts in any microcredential are mastered → create `pending_credential`
6. Faculty reviews pending credentials and approves → OB3 JSON-LD credential generated

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Orchestrator | Python, FastAPI, LangGraph, Claude API |
| MCP Servers | Python, asyncpg, MCP SDK (SSE transport) |
| Database | PostgreSQL 16 + pgvector |
| Chat Frontend | Next.js 16, React 19, Tailwind CSS, react-markdown |
| Ultra Frontend | Next.js 16, React 19, Tailwind CSS, Lucide icons |
| TTS | Fish Audio S2 (multi-speaker podcast generation) |
| Code Execution | Pyodide (Python WASM in browser) |
| Diagrams | Mermaid.js (rendered in chat) |
| Observability | OpenTelemetry → Tempo (traces) + Prometheus (metrics) → Grafana |
| Containers | Docker Compose, 14 services |

## Three Enforcement Layers

### Layer 1: MCP Tool Guardrails
Hard rules at the data layer. Agents cannot bypass these.
- **Mastery timing**: `attestations.attest` auto-downgrades mastery to proficient if no prior attestation from a different session
- **Prerequisite soft gate**: `content.get_skill` returns prerequisite gaps when prerequisites aren't satisfied
- **Session tracking**: All attestations and conversation turns include `session_id`

### Layer 2: Orchestrator Lifecycle Hooks
Session flow events injected by the orchestrator before agent dispatch.
- **Retrieval practice**: First turn of each session, inject 2-3 proficient concepts for cold recall testing
- **Revision loops**: Track failed assessments, inject reminders on subsequent turns
- **Interleaving**: Every 3-4 turns, suggest cross-concept problems when student is doing well
- **Session end**: Detect goodbye intent, inject metacognitive reflection prompt

### Layer 3: Learning Analyst Agent
Background agent that runs after every student session.
- **Shallow review** (Haiku): session summary, profile update, review flags, student insights
- **Deep review** (Sonnet): triggered by contradictions, regressions, milestones, or 20% random chance. Analyzes 10-20 session transcripts for longitudinal patterns.
- **Profile reconciliation**: course-tagged observations, contradiction resolution, stale trimming

## Key Design Decisions

**No grades.** The system uses mastery attestation levels (not_started → emerging → proficient → mastery). Each level has clear criteria and different implications.

**Proficient is not mastery.** A student who answers correctly in the same session they learn a concept gets proficient, not mastery. Mastery requires demonstrating understanding in a later session through transfer, integration, teach-back, debugging, or edge-case challenges.

**The tutor doesn't write to the learner profile.** The Learning Analyst handles profile updates post-session, enabling reconciliation across sessions and courses without in-the-moment bias.

**Podcasts are personalized.** Generated from the student's current mastery state, using concepts they're actively working on. Fish Audio S2 renders multi-speaker conversations (host + expert).

**Two UIs, one backend.** Both the chat-first UI and the Ultra UI connect to the same orchestrator and share the same data. The page brief pattern provides persona-specific data on session creation.
