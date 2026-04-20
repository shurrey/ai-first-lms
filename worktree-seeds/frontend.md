# CLAUDE.md — Frontend worktree

You are the Frontend agent. Your workstream is defined in SPEC.md §10 "Workstream 4 — Frontend". You own `src/frontend/` and nothing else.

## Your mission

Build the Next.js 14 app per SPEC.md §7. Three panels:
- Left: persona/course context
- Center: chat
- Right: agent-activity tree + result canvas (rubric, quiz, chart, message, degree audit, learning-graph path)

Your UI talks ONLY to the orchestrator via `contracts/api.openapi.yaml`. SSE events land via `GET /api/stream` following `contracts/events.md`. Approvals go via `POST /api/approval`. Clarifications via `POST /api/clarify`.

## Your rules

Same as Engine. Key points for you:

- Stay in `src/frontend/**`.
- Contracts are law. The only way to learn about new events or endpoints is contract change (T-C task).
- You do not invent event types. You render what the stream gives you.
- Playwright E2E tests for scenarios 1, 3, 10, 11 are non-negotiable.

## Your loop

Standard loop, scoped to `T-F-*`.

## Where to start

Read:
1. `SPEC.md` — §1, §2, §7, §8, §10, §11
2. `contracts/api.openapi.yaml`
3. `contracts/events.md`
4. `TASKS.md`

First claim: `T-F-001 — Next.js 14 scaffold`. Before claiming anything else, make sure `pnpm dev` boots a clean app and the API mock fixture renders.

## Tech

- Next.js 14 App Router
- TypeScript strict
- Tailwind + shadcn/ui (install via `pnpm dlx shadcn-ui@latest init`)
- `@tanstack/react-query` for request state
- `eventsource-parser` for SSE
- `recharts` for charts
- `zod` for event-envelope validation at the boundary

## Layout

```
src/frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                 # the three-panel app
│   └── api/                     # no backend routes; everything hits orchestrator
├── components/
│   ├── ContextPane/
│   ├── ChatPane/
│   ├── ActivityPane/
│   ├── Canvas/
│   │   ├── RubricCanvas.tsx
│   │   ├── QuizCanvas.tsx
│   │   ├── ChartCanvas.tsx
│   │   ├── MessageCanvas.tsx
│   │   ├── DegreeAuditCanvas.tsx
│   │   ├── LearningPathCanvas.tsx
│   │   ├── WCAGReportCanvas.tsx
│   │   └── RiskListCanvas.tsx
│   └── ApprovalGate.tsx
├── lib/
│   ├── sse.ts                   # SSE client + ringbuffer + reconnect
│   ├── api.ts                   # REST calls
│   └── events.ts                # zod schemas matching contracts/events.md
├── tests/
│   ├── unit/
│   └── e2e/                     # Playwright scenario tests
└── styles/
```

## Streaming and ringbuffer

The SSE stream can deliver events out of order (rarely), and reconnects must pick up correctly. The ringbuffer pattern:

```typescript
type Ring = Map<number /*sequence*/, Event>;
let maxSeen = 0;
let nextEmit = 1;

function onEvent(ev: Event) {
  ring.set(ev.sequence, ev);
  maxSeen = Math.max(maxSeen, ev.sequence);
  while (ring.has(nextEmit)) {
    emitToUI(ring.get(nextEmit)!);
    ring.delete(nextEmit);
    nextEmit++;
  }
}

function onReconnect() {
  // GET /api/stream?since_sequence=nextEmit
}
```

This guarantees strict ordered emission to the UI despite transport noise.

## Canvas items are interactive

Each canvas renderer receives an artifact and a `status: "draft" | "awaiting_approval" | "approved" | "rejected"`. The approval UX:

- `draft`: shows the artifact, no action buttons
- `awaiting_approval`: Approve / Edit / Reject buttons active; clicking Approve posts the artifact payload; Edit opens an inline editor; Reject prompts for a note
- `approved` / `rejected`: shows the final state with a badge

## Persona UX

The persona switcher changes:
- Which suggested-prompt pills appear
- How the canvas renders (student sees a study guide as a document; faculty sees it with editorial controls)
- Which portions of the context pane are visible

The persona does NOT gate data access from the frontend. Enforcement is at the orchestrator. Frontend enforcement would be security theater.

## Hard constraints

- No mocking of the orchestrator in production code paths. Mocks only in tests.
- No local state that duplicates server state. Use react-query.
- No secrets or API keys in the frontend. The orchestrator is the only trusted boundary.
- `any` types require an inline comment justifying them.
- Every `agent_tool_call` event must render with the tool name visible — transparency is a product principle.
