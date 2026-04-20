# Course Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a student opens a course, automatically generate a dashboard card in the sidebar and a proactive coaching message in the chat — no user action required.

**Architecture:** `POST /api/session` fires a background `BriefGenerator` that calls MCP tools for raw data, builds a structured `brief_card` event for the sidebar, then calls Claude once to generate a coaching chat message emitted as a `final` event. The frontend connects to the brief's stream immediately after session creation.

**Tech Stack:** Python (FastAPI, MCP SSE client, Anthropic SDK), TypeScript (React, Next.js, Zod, TanStack Query)

---

### Task 1: Backend — BriefGenerator + StudentBriefGatherer

**Files:**
- Create: `src/engine/brief.py`

- [ ] **Step 1: Create `src/engine/brief.py`**

```python
"""Course brief generator — auto-summary when a session starts."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

import anthropic
import httpx

logger = logging.getLogger(__name__)

_MCP_SERVERS = {
    "roster": "http://mcp-roster:7002",
    "assessments": "http://mcp-assessments:7003",
    "content": "http://mcp-content:7001",
}

COACHING_SYSTEM_PROMPT = """\
You are the Tutor in an AI-native LMS. A student just opened their course.
Write a brief, warm, proactive greeting (2-4 sentences).
Be specific about their real data — mention their name, scores, upcoming work.
Highlight the most urgent or impactful item.
End with a concrete offer to help with something specific.
Do NOT use JSON. Write plain markdown only.
Do NOT use emojis excessively — one or two is fine.
"""


class BriefGatherer(Protocol):
    """Protocol for persona-specific data gathering."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]: ...

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]: ...


async def _call_mcp(server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and return parsed JSON result."""
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    base_url = _MCP_SERVERS.get(server, "")
    if not base_url:
        return {"error": f"Unknown server: {server}"}
    try:
        async with sse_client(f"{base_url}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                for item in result.content:
                    if hasattr(item, "text"):
                        return json.loads(item.text)
                return {}
    except Exception as exc:
        logger.warning("MCP call %s failed: %s", tool, exc)
        return {"error": str(exc)}


class StudentBriefGatherer:
    """Gathers brief data for a student persona."""

    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]:
        # Gather data from MCP servers in parallel-ish (sequential for simplicity)
        student_ctx = await _call_mcp(
            "roster", "roster.get_student_context",
            {"person_id": person_id, "course_id": course_id},
        )
        evidence = await _call_mcp(
            "assessments", "assessments.list_recent_evidence",
            {"person_id": person_id, "course_id": course_id},
        )
        modules = await _call_mcp(
            "content", "content.list_modules",
            {"course_id": course_id},
        )

        return {
            "student_ctx": student_ctx,
            "evidence": evidence,
            "modules": modules,
        }

    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        student_ctx = raw_data.get("student_ctx", {})
        evidence_data = raw_data.get("evidence", {})
        modules_data = raw_data.get("modules", {})

        # Extract student name
        student_name = student_ctx.get("display_name", "Student")
        course_title = student_ctx.get("course_title", "")

        # Build assignments from evidence
        evidence_list = evidence_data.get("evidence", evidence_data.get("recent_evidence", []))
        assignments = []
        scores = []
        for ev in evidence_list:
            title = ev.get("title", ev.get("kind", "Unknown"))
            score = ev.get("score")
            assignments.append({
                "title": title,
                "status": "attempted" if score is not None else "not_started",
                "score": round(score, 2) if score is not None else None,
            })
            if score is not None:
                scores.append(score)

        # Module info
        module_list = modules_data.get("modules", [])
        total_modules = len(module_list)

        avg_score = round(sum(scores) / len(scores), 2) if scores else 0

        # Generate suggested actions based on data
        suggested_actions = []
        # Find lowest score assignment
        if assignments:
            worst = min((a for a in assignments if a["score"] is not None), key=lambda a: a["score"], default=None)
            if worst and worst["score"] is not None and worst["score"] < 0.5:
                suggested_actions.append({
                    "label": f"Review: {worst['title']}",
                    "prompt": f"Help me understand what I got wrong on {worst['title']}",
                })
        suggested_actions.append({
            "label": "Find my weak spots",
            "prompt": "What am I weakest at in this course?",
        })
        suggested_actions.append({
            "label": "Study next topic",
            "prompt": "What should I study next?",
        })

        return {
            "persona": "student",
            "student_name": student_name,
            "course_title": course_title,
            "current_module": {
                "title": module_list[0]["title"] if module_list else "Unknown",
                "index": 1,
                "total": total_modules,
            },
            "assignments": assignments[:10],
            "stats": {
                "avg_score": avg_score,
                "submissions_count": len(scores),
                "total_assignments": len(assignments),
            },
            "suggested_actions": suggested_actions,
        }


class BriefGenerator:
    """Generates a course brief (card + coaching message) for any persona."""

    _gatherers: dict[str, BriefGatherer] = {
        "student": StudentBriefGatherer(),
    }

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            http_client=httpx.AsyncClient(verify=False),
        )

    async def generate(
        self,
        persona: str,
        person_id: str,
        course_id: str,
        turn_id: str,
        turn_store: Any,
    ) -> None:
        gatherer = self._gatherers.get(persona)
        if not gatherer:
            # No brief for this persona yet — silently complete
            await turn_store.update_status(turn_id, "completed")
            return

        try:
            raw_data = await gatherer.gather(person_id, course_id)
            card = gatherer.build_card(raw_data)

            # Generate coaching message via Claude
            chat_msg = await self._coaching_message(raw_data)

            events = [
                {"event": "brief_card", "payload": card},
                {
                    "event": "final",
                    "payload": {
                        "answer_markdown": chat_msg,
                        "artifacts": [],
                        "cost_usd": 0.0,
                        "tokens": 0,
                        "wall_time_ms": 0.0,
                    },
                },
            ]
            await turn_store.add_events(turn_id, events)
            await turn_store.update_status(turn_id, "completed")

        except Exception as exc:
            logger.exception("Brief generation failed: %s", exc)
            await turn_store.add_events(turn_id, [{
                "event": "final",
                "payload": {
                    "answer_markdown": "Welcome to your course! Ask me anything to get started.",
                    "artifacts": [],
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "wall_time_ms": 0.0,
                },
            }])
            await turn_store.update_status(turn_id, "completed")

    async def _coaching_message(self, raw_data: dict[str, Any]) -> str:
        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                system=COACHING_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"Student data:\n{json.dumps(raw_data, indent=2, default=str)}",
                }],
                max_tokens=300,
            )
            return response.content[0].text
        except Exception as exc:
            logger.warning("Coaching message generation failed: %s", exc)
            return "Welcome to your course! I'm your tutor — ask me anything to get started."
```

- [ ] **Step 2: Commit**

```bash
git add src/engine/brief.py
git commit -m "feat(engine): add BriefGenerator with StudentBriefGatherer for course briefs"
```

---

### Task 2: Backend — Wire Brief into Session Endpoint

**Files:**
- Modify: `src/engine/models/session.py`
- Modify: `src/engine/api/session.py`

- [ ] **Step 1: Update session response model**

In `src/engine/models/session.py`, replace `CreateSessionResponse`:

```python
class CreateSessionResponse(BaseModel):
    session_id: str
    brief_turn_id: str | None = None
    stream_url: str | None = None
```

- [ ] **Step 2: Update session endpoint to fire brief**

Replace `src/engine/api/session.py` with:

```python
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from engine.models.session import CreateSessionRequest, CreateSessionResponse, Session
from engine.models.turn import Turn

router = APIRouter()

VALID_PERSONAS = {"student", "faculty", "advisor", "admin"}

_COURSE_SLUG_TO_UUID: dict[str, str] = {
    "cs101": "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
}

_DEMO_STUDENTS: dict[str, tuple[str, str]] = {
    "bdd640fb-0667-4ad1-9c80-317fa3b1799d": (
        "17fc695a-07a0-4a6e-8822-e8f36c031199", "Emma Smith"
    ),
}


@router.post("/api/session", status_code=201, response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    if body.persona not in VALID_PERSONAS:
        raise HTTPException(status_code=422, detail=f"Invalid persona: {body.persona}")

    course_id = _COURSE_SLUG_TO_UUID.get(body.course_id, body.course_id)

    person_id = body.person_id
    if not person_id and body.persona == "student" and course_id in _DEMO_STUDENTS:
        person_id = _DEMO_STUDENTS[course_id][0]

    session = Session(
        persona=body.persona,
        person_id=person_id,
        course_id=course_id,
    )
    store = request.app.state.session_store
    await store.create(session)

    # Create a brief turn and fire generation in background
    brief_turn_id = f"brief-{session.id}"
    brief_turn = Turn(session_id=session.id, message="__brief__")
    brief_turn.id = brief_turn_id
    turn_store = request.app.state.turn_store
    await turn_store.create(brief_turn)

    if person_id:
        from engine.brief import BriefGenerator
        generator = BriefGenerator()
        asyncio.create_task(
            generator.generate(
                persona=body.persona,
                person_id=person_id,
                course_id=course_id,
                turn_id=brief_turn_id,
                turn_store=turn_store,
            )
        )

    stream_url = f"/api/stream?session_id={session.id}&turn_id={brief_turn_id}"

    return CreateSessionResponse(
        session_id=session.id,
        brief_turn_id=brief_turn_id,
        stream_url=stream_url,
    )
```

- [ ] **Step 3: Commit**

```bash
git add src/engine/models/session.py src/engine/api/session.py
git commit -m "feat(engine): fire brief generation on session creation, return stream_url"
```

---

### Task 3: Frontend — Add brief_card Event Type

**Files:**
- Modify: `src/frontend/lib/events.ts`

- [ ] **Step 1: Add brief_card to EventType and payload schemas**

In `src/frontend/lib/events.ts`:

Add `"brief_card"` to the `EventType` enum (line 4):

```typescript
export const EventType = z.enum([
  "reasoning",
  "plan",
  "agent_start",
  "agent_token",
  "agent_tool_call",
  "agent_result",
  "clarify",
  "approval_request",
  "brief_card",
  "final",
  "error",
]);
```

Add the `BriefCardPayload` schema after `ApprovalRequestPayload` (around line 90):

```typescript
export const BriefAssignment = z.object({
  title: z.string(),
  status: z.string(),
  score: z.number().nullable(),
});

export const BriefSuggestedAction = z.object({
  label: z.string(),
  prompt: z.string(),
});

export const BriefCardPayload = z.object({
  persona: z.string(),
  student_name: z.string(),
  course_title: z.string(),
  current_module: z.object({
    title: z.string(),
    index: z.number(),
    total: z.number(),
  }),
  assignments: z.array(BriefAssignment),
  stats: z.object({
    avg_score: z.number(),
    submissions_count: z.number(),
    total_assignments: z.number(),
  }),
  suggested_actions: z.array(BriefSuggestedAction),
});
```

Add to `PAYLOAD_SCHEMAS` (around line 146):

```typescript
const PAYLOAD_SCHEMAS: Record<string, z.ZodType> = {
  reasoning: ReasoningPayload,
  plan: PlanPayload,
  agent_start: AgentStartPayload,
  agent_token: AgentTokenPayload,
  agent_tool_call: AgentToolCallPayload,
  agent_result: AgentResultPayload,
  clarify: ClarifyPayload,
  approval_request: ApprovalRequestPayload,
  brief_card: BriefCardPayload,
  final: FinalPayload,
  error: ErrorPayload,
};
```

Add type exports at the bottom:

```typescript
export type BriefCardPayload = z.infer<typeof BriefCardPayload>;
export type BriefAssignment = z.infer<typeof BriefAssignment>;
export type BriefSuggestedAction = z.infer<typeof BriefSuggestedAction>;
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/lib/events.ts
git commit -m "feat(frontend): add brief_card event type and Zod schema"
```

---

### Task 4: Frontend — BriefCard Component

**Files:**
- Create: `src/frontend/components/BriefCard/BriefCard.tsx`

- [ ] **Step 1: Create the BriefCard component**

```tsx
"use client";

import type { BriefCardPayload } from "@/lib/events";

interface BriefCardProps {
  data: BriefCardPayload;
  onAction?: (prompt: string) => void;
}

export function BriefCard({ data, onAction }: BriefCardProps) {
  const progressPct = data.current_module.total > 0
    ? Math.round((data.current_module.index / data.current_module.total) * 100)
    : 0;

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      {/* Header */}
      <div>
        <p className="text-sm font-semibold">{data.student_name}</p>
        <p className="text-xs text-muted-foreground">{data.course_title}</p>
      </div>

      {/* Progress */}
      <div>
        <div className="mb-1 flex justify-between text-xs text-muted-foreground">
          <span>Module {data.current_module.index} of {data.current_module.total}</span>
          <span>{data.current_module.title}</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-muted">
          <div
            className="h-1.5 rounded-full bg-primary transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Assignments */}
      {data.assignments.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Assignments
          </p>
          <div className="space-y-1">
            {data.assignments.map((a, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{a.title}</span>
                <span className={`shrink-0 font-mono ${
                  a.score !== null && a.score < 0.5
                    ? "text-destructive"
                    : a.score !== null
                    ? "text-green-600 dark:text-green-400"
                    : "text-muted-foreground"
                }`}>
                  {a.score !== null ? `${Math.round(a.score * 100)}%` : "--"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="flex gap-3 text-xs text-muted-foreground">
        <span>Avg: {Math.round(data.stats.avg_score * 100)}%</span>
        <span>{data.stats.submissions_count}/{data.stats.total_assignments} submitted</span>
      </div>

      {/* Suggested Actions */}
      {data.suggested_actions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.suggested_actions.map((action, i) => (
            <button
              key={i}
              onClick={() => onAction?.(action.prompt)}
              className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors"
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/components/BriefCard/BriefCard.tsx
git commit -m "feat(frontend): add BriefCard component for course dashboard sidebar"
```

---

### Task 5: Frontend — Wire Brief Stream on Session Creation

**Files:**
- Modify: `src/frontend/lib/api.ts`
- Modify: `src/frontend/lib/session-context.tsx`
- Modify: `src/frontend/lib/turn-context.tsx`
- Modify: `src/frontend/components/ContextPane/CourseSelector.tsx`
- Modify: `src/frontend/components/ChatPane/ChatPane.tsx`
- Modify: `src/frontend/components/ActivityPane/ActivityPane.tsx`

- [ ] **Step 1: Update API response type**

In `src/frontend/lib/api.ts`, update `createSession` return type:

```typescript
export async function createSession(
  persona: Persona,
  courseId: string,
  personId?: string
): Promise<{ session_id: string; brief_turn_id: string | null; stream_url: string | null }> {
  const res = await fetch(`${API_BASE}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      persona,
      course_id: courseId,
      ...(personId && { person_id: personId }),
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to create session: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: Add briefTurnId to session context**

In `src/frontend/lib/session-context.tsx`, add `briefTurnId` to state:

```tsx
"use client";

import { createContext, useContext, useCallback, useState } from "react";

export type Persona = "student" | "faculty" | "advisor" | "admin";

interface SessionState {
  persona: Persona;
  courseId: string | null;
  sessionId: string | null;
  briefTurnId: string | null;
  setPersona: (p: Persona) => void;
  setCourseId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  setBriefTurnId: (id: string | null) => void;
  resetSession: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona>("student");
  const [courseId, setCourseId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [briefTurnId, setBriefTurnId] = useState<string | null>(null);

  const resetSession = useCallback(() => {
    setSessionId(null);
    setBriefTurnId(null);
  }, []);

  return (
    <SessionContext.Provider
      value={{
        persona,
        courseId,
        sessionId,
        briefTurnId,
        setPersona,
        setCourseId,
        setSessionId,
        setBriefTurnId,
        resetSession,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
```

- [ ] **Step 3: Update CourseSelector to store briefTurnId**

In `src/frontend/components/ContextPane/CourseSelector.tsx`, update the mutation's onSuccess:

```tsx
const createSessionMutation = useMutation({
  mutationFn: (selectedCourseId: string) =>
    createSession(persona, selectedCourseId),
  onSuccess: (data) => {
    setSessionId(data.session_id);
    setBriefTurnId(data.brief_turn_id ?? null);
  },
});
```

Update the destructure at the top:

```tsx
const { persona, courseId, setCourseId, setSessionId, setBriefTurnId } = useSession();
```

- [ ] **Step 4: Auto-start brief turn in TurnProvider**

In `src/frontend/lib/turn-context.tsx`, add a `briefCardData` state and auto-start the brief stream when `briefTurnId` arrives:

```tsx
"use client";

import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { useSession } from "./session-context";
import { useEventStream, type TurnState } from "./use-event-stream";
import type { BriefCardPayload } from "./events";

interface TurnContextValue extends TurnState {
  activeTurnId: string | null;
  briefCardData: BriefCardPayload | null;
  startTurn: (turnId: string) => void;
}

const TurnContext = createContext<TurnContextValue | null>(null);

export function TurnProvider({ children }: { children: React.ReactNode }) {
  const { sessionId, briefTurnId } = useSession();
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [briefCardData, setBriefCardData] = useState<BriefCardPayload | null>(null);

  // When briefTurnId arrives, start streaming it
  useEffect(() => {
    if (briefTurnId && !activeTurnId) {
      setActiveTurnId(briefTurnId);
    }
  }, [briefTurnId, activeTurnId]);

  const turnState = useEventStream(sessionId, activeTurnId);

  // Capture brief_card events from the stream
  useEffect(() => {
    if (turnState.briefCard) {
      setBriefCardData(turnState.briefCard);
    }
  }, [turnState.briefCard]);

  const startTurn = useCallback((turnId: string) => {
    setActiveTurnId(turnId);
  }, []);

  return (
    <TurnContext.Provider value={{ ...turnState, activeTurnId, briefCardData, startTurn }}>
      {children}
    </TurnContext.Provider>
  );
}

export function useTurn(): TurnContextValue {
  const ctx = useContext(TurnContext);
  if (!ctx) throw new Error("useTurn must be used within TurnProvider");
  return ctx;
}
```

- [ ] **Step 5: Add briefCard to TurnState in use-event-stream**

In `src/frontend/lib/use-event-stream.ts`, add `briefCard` to the state and handle `brief_card` events in the reducer. Find the TurnState interface and add:

```typescript
briefCard: BriefCardPayload | null;
```

In the initial state, add:

```typescript
briefCard: null,
```

In the reducer's event handler, add a case for `brief_card`:

```typescript
case "brief_card":
  return { ...state, briefCard: event.payload as BriefCardPayload };
```

(The exact lines depend on the reducer structure — the implementer should find the `switch` or `if/else` on `event.event` and add this case.)

- [ ] **Step 6: Wire BriefCard into ActivityPane**

In `src/frontend/components/ActivityPane/ActivityPane.tsx`, add the BriefCard at the top of the sidebar:

```tsx
"use client";

import { ActivityTree } from "./ActivityTree";
import { BriefCard } from "@/components/BriefCard/BriefCard";
import { CanvasRouter } from "@/components/Canvas/CanvasRouter";
import { ApprovalGate } from "@/components/ApprovalGate";
import { useTurn } from "@/lib/turn-context";
import { converse } from "@/lib/api";
import { useSession } from "@/lib/session-context";

export function ActivityPane() {
  const turn = useTurn();
  const { sessionId } = useSession();
  const artifacts = turn.finalResult?.artifacts ?? [];

  const handleBriefAction = (prompt: string) => {
    if (!sessionId) return;
    converse(sessionId, prompt).then((data) => {
      turn.startTurn(data.turn_id);
    });
  };

  return (
    <aside className="flex h-full flex-col overflow-y-auto border-l border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Activity
      </h2>
      <div className="flex-1 space-y-4">
        {/* Course brief card */}
        {turn.briefCardData && (
          <BriefCard data={turn.briefCardData} onAction={handleBriefAction} />
        )}

        <ActivityTree />

        {turn.approval && (
          <div className="space-y-3">
            <CanvasRouter
              artifact={{
                artifact_id: turn.approval.approval_id,
                type: turn.approval.artifact_type,
                data: turn.approval.preview,
              }}
              status="awaiting_approval"
            />
            <ApprovalGate
              approvalId={turn.approval.approval_id}
              action={turn.approval.action}
              preview={turn.approval.preview}
            />
          </div>
        )}

        {artifacts.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Artifacts
            </h3>
            {artifacts.map((artifact) => (
              <CanvasRouter
                key={artifact.artifact_id}
                artifact={artifact}
                status="approved"
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 7: Commit all frontend wiring**

```bash
git add src/frontend/lib/api.ts src/frontend/lib/session-context.tsx src/frontend/lib/turn-context.tsx src/frontend/components/ContextPane/CourseSelector.tsx src/frontend/components/ActivityPane/ActivityPane.tsx
git commit -m "feat(frontend): wire brief stream to session creation, render BriefCard in sidebar"
```

---

### Task 6: Build, Deploy, and Smoke Test

- [ ] **Step 1: Rebuild orchestrator**

```bash
docker compose build orchestrator 2>&1 | tail -5
docker compose up -d orchestrator 2>&1 | tail -3
```

- [ ] **Step 2: Rebuild frontend**

```bash
docker compose build frontend 2>&1 | tail -5
docker compose up -d frontend 2>&1 | tail -3
```

- [ ] **Step 3: Test the brief via API**

```bash
# Create a session — should return brief_turn_id and stream_url
curl -s -X POST http://localhost:8000/api/session \
  -H "Content-Type: application/json" \
  -d '{"persona":"student","course_id":"cs101"}'
```

Expected: `{"session_id":"...","brief_turn_id":"brief-...","stream_url":"/api/stream?..."}`

- [ ] **Step 4: Check brief stream**

```bash
# Wait a few seconds for brief to generate, then check events
sleep 15 && curl -s -m 5 "http://localhost:8000/api/stream?session_id=<session_id>&turn_id=brief-<session_id>&since_sequence=0" | head -20
```

Expected: `brief_card` event with student data, then `final` event with coaching message.

- [ ] **Step 5: Test in browser**

Open http://localhost:3000, select CS 101 as a student. Expected:
- Sidebar populates with BriefCard (Emma Smith, assignments, scores, action buttons)
- Chat shows a proactive greeting from the tutor
- Clicking an action button in the card sends that prompt to the chat

- [ ] **Step 6: Fix any issues and commit**

If events arrive but frontend doesn't render them, check:
- The `brief_card` event type is handled in the `use-event-stream` reducer
- The `BriefCardPayload` Zod schema matches the backend's actual payload
- The `briefCard` field is exposed on `TurnContextValue`
