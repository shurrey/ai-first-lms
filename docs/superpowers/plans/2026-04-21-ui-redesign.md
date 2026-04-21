# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-column layout with a two-column layout featuring inline thinking blocks in the chat and a persistent persona-specific course context panel.

**Architecture:** Three phases — (1) backend: add `thinking` event type and fix status message bug, (2) frontend layout: new header nav + two-column grid + thinking drawer, (3) frontend panels: persona-specific right panels with drill-down states. Each phase produces working software.

**Tech Stack:** Python (FastAPI), TypeScript (React, Next.js, Zod, Tailwind), SSE streaming

---

## Phase 1: Backend — Thinking Events + Status Message Fix

### Task 1: Emit thinking events from agent tool-use text

**Files:**
- Modify: `src/engine/agents/runner.py`

The runner's `_tool_loop` currently ignores text blocks from `stop_reason: "tool_use"` responses. These are agent status messages ("I have all 50 students. Now let me fetch evidence..."). They should be captured and returned as `thinking_messages` in the result dict.

- [ ] **Step 1: Capture text blocks from tool_use responses**

In `src/engine/agents/runner.py`, find the `_tool_loop` method. Inside the `if response.stop_reason == "tool_use":` block, after `messages.append({"role": "assistant", "content": response.content})`, add extraction of text blocks:

```python
                if response.stop_reason == "tool_use":
                    # Add assistant message with all content blocks
                    messages.append({"role": "assistant", "content": response.content})

                    # Capture any text blocks as thinking/status messages
                    for block in response.content:
                        if block.type == "text" and block.text.strip():
                            tool_call_records.append({
                                "tool": "__thinking__",
                                "arguments": {},
                                "result_summary": block.text.strip()[:200],
                                "latency_ms": 0,
                                "success": True,
                            })

                    # Execute each tool call
```

This reuses the existing `tool_call_records` list with a sentinel tool name `__thinking__` so thinking messages flow through the same event pipeline.

- [ ] **Step 2: Commit**

```bash
git add src/engine/agents/runner.py
git commit -m "feat(engine): capture agent thinking/status text from tool_use responses"
```

---

### Task 2: Emit thinking events in dispatch

**Files:**
- Modify: `src/engine/graph/dispatch.py`

The dispatch step emits `agent_tool_call` events for each tool call record. Records with `tool: "__thinking__"` should be emitted as `thinking` events instead.

- [ ] **Step 1: Add thinking event emission**

In `src/engine/graph/dispatch.py`, in the `_execute_step` function, find the loop that emits tool_call events (around line 139-151). Change it to handle thinking records:

```python
    # Emit tool_call and thinking events
    for tc in result.get("tool_calls", []):
        if tc.get("tool") == "__thinking__":
            step_events.append({
                "event": "thinking",
                "payload": {
                    "step_id": step_id,
                    "agent": agent,
                    "text": tc.get("result_summary", ""),
                },
            })
        else:
            step_events.append({
                "event": "agent_tool_call",
                "payload": {
                    "step_id": step_id,
                    "agent": agent,
                    "tool": tc.get("tool", "unknown"),
                    "arguments": tc.get("arguments", {}),
                    "result_summary": tc.get("result_summary", ""),
                    "latency_ms": tc.get("latency_ms", 0),
                    "success": tc.get("success", True),
                },
            })
```

- [ ] **Step 2: Commit**

```bash
git add src/engine/graph/dispatch.py
git commit -m "feat(engine): emit thinking events for agent status messages"
```

---

### Task 3: Add thinking event type to frontend

**Files:**
- Modify: `src/frontend/lib/events.ts`
- Modify: `src/frontend/lib/use-event-stream.ts`

- [ ] **Step 1: Add thinking to EventType enum and payload schema**

In `src/frontend/lib/events.ts`, add `"thinking"` to the EventType enum (before `"final"`):

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
  "thinking",
  "final",
  "error",
]);
```

Add ThinkingPayload schema (after BriefCardPayload):

```typescript
export const ThinkingPayload = z.object({
  step_id: z.string(),
  agent: z.string(),
  text: z.string(),
});
```

Add to PAYLOAD_SCHEMAS:

```typescript
  thinking: ThinkingPayload,
```

Add type export:

```typescript
export type ThinkingPayload = z.infer<typeof ThinkingPayload>;
```

- [ ] **Step 2: Add thinkingMessages to TurnState**

In `src/frontend/lib/use-event-stream.ts`, add to the TurnState interface:

```typescript
thinkingMessages: string[];
```

Add to initialState:

```typescript
thinkingMessages: [],
```

Add case to the reducer:

```typescript
        case "thinking":
          return {
            ...state,
            thinkingMessages: [
              ...state.thinkingMessages,
              (payload as ThinkingPayload).text,
            ],
          };
```

- [ ] **Step 3: Commit**

```bash
git add src/frontend/lib/events.ts src/frontend/lib/use-event-stream.ts
git commit -m "feat(frontend): add thinking event type to event stream"
```

---

## Phase 2: Frontend Layout — Header + Two-Column + Thinking Drawer

### Task 4: Create Header component with persona-specific navigation

**Files:**
- Create: `src/frontend/components/Header/Header.tsx`

- [ ] **Step 1: Create the Header component**

```tsx
"use client";

import { useSession, type Persona } from "@/lib/session-context";
import { useMutation } from "@tanstack/react-query";
import { createSession } from "@/lib/api";

const PERSONAS: { value: Persona; label: string }[] = [
  { value: "student", label: "Student" },
  { value: "faculty", label: "Faculty" },
  { value: "advisor", label: "Advisor" },
  { value: "admin", label: "Admin" },
];

const COURSES = [
  { id: "cs101", name: "CS 101 — Intro to Computer Science" },
  { id: "math201", name: "MATH 201 — Linear Algebra" },
  { id: "eng102", name: "ENG 102 — Academic Writing" },
  { id: "bio150", name: "BIO 150 — General Biology" },
];

export function Header() {
  const {
    persona, courseId, sessionId,
    setPersona, setCourseId, setSessionId, setBriefTurnId, resetSession,
  } = useSession();

  const createSessionMutation = useMutation({
    mutationFn: ({ p, c }: { p: Persona; c: string }) => createSession(p, c),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setBriefTurnId(data.brief_turn_id ?? null);
    },
  });

  const handleCourseChange = (newCourseId: string) => {
    setCourseId(newCourseId || null);
    if (newCourseId) {
      createSessionMutation.mutate({ p: persona, c: newCourseId });
    }
  };

  const handlePersonaChange = (newPersona: Persona) => {
    setPersona(newPersona);
    resetSession();
    if (courseId) {
      createSessionMutation.mutate({ p: newPersona, c: courseId });
    }
  };

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      <h1 className="text-sm font-semibold tracking-tight">AI-First LMS</h1>
      <span className="text-border">·</span>

      {/* Course dropdown */}
      <select
        value={courseId ?? ""}
        onChange={(e) => handleCourseChange(e.target.value)}
        className="rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
      >
        <option value="">Select a course...</option>
        {(persona === "advisor" || persona === "admin") && (
          <option value="all">All Courses</option>
        )}
        {COURSES.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>

      <div className="ml-auto flex items-center gap-2">
        {/* Persona switcher */}
        <select
          value={persona}
          onChange={(e) => handlePersonaChange(e.target.value as Persona)}
          className="rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
        >
          {PERSONAS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>

        {sessionId && (
          <span className="text-xs text-muted-foreground truncate max-w-[120px]">
            {sessionId.slice(0, 8)}...
          </span>
        )}
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/components/Header/Header.tsx
git commit -m "feat(frontend): add Header component with persona-specific navigation"
```

---

### Task 5: Create ThinkingDrawer component

**Files:**
- Create: `src/frontend/components/ChatPane/ThinkingDrawer.tsx`

- [ ] **Step 1: Create the ThinkingDrawer component**

```tsx
"use client";

import { useState } from "react";
import type { AgentToolCallPayload } from "@/lib/events";

interface ThinkingStep {
  type: "reasoning" | "tool_call" | "thinking";
  text: string;
  tool?: string;
  latencyMs?: number;
  success?: boolean;
}

interface ThinkingDrawerProps {
  steps: ThinkingStep[];
  isStreaming: boolean;
  tokenCount?: number;
  toolCallCount?: number;
}

export function ThinkingDrawer({ steps, isStreaming, tokenCount, toolCallCount }: ThinkingDrawerProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0) return null;

  // While streaming, show expanded live view
  if (isStreaming) {
    return (
      <div className="mb-2 mr-[20%] space-y-1">
        {steps.map((step, i) => (
          <ThinkingStepBlock key={i} step={step} />
        ))}
      </div>
    );
  }

  // After completion, show collapsible drawer
  const toolCalls = steps.filter((s) => s.type === "tool_call").length;
  const summary = `${toolCalls} tool call${toolCalls !== 1 ? "s" : ""}${tokenCount ? ` · ${Math.round(tokenCount / 1000)}k tokens` : ""}`;

  return (
    <div className="mb-2 mr-[20%] overflow-hidden rounded-lg border border-purple-200 bg-purple-50/50 dark:border-purple-900 dark:bg-purple-950/20">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs"
      >
        <span className="text-[10px] text-purple-500">{expanded ? "▼" : "▶"}</span>
        <span className="font-medium text-purple-700 dark:text-purple-300">Thinking</span>
        <span className="ml-auto text-[10px] text-muted-foreground">{summary}</span>
      </button>
      {expanded && (
        <div className="border-t border-purple-200 px-3 py-2 dark:border-purple-900">
          <div className="space-y-0.5">
            {steps.map((step, i) => (
              <ThinkingStepBlock key={i} step={step} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ThinkingStepBlock({ step }: { step: ThinkingStep }) {
  if (step.type === "tool_call") {
    return (
      <div className="flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-950/30">
        <span>⚡</span>
        <span>{step.tool}</span>
        {step.latencyMs !== undefined && (
          <span className="text-muted-foreground">— {Math.round(step.latencyMs)}ms</span>
        )}
        <span>{step.success ? "✓" : "✗"}</span>
      </div>
    );
  }

  // reasoning or thinking
  const icon = step.type === "thinking" ? "💬" : "🔍";
  return (
    <div className="flex items-start gap-1.5 rounded px-2 py-0.5 text-[10px] text-purple-700 bg-purple-50/50 dark:text-purple-300 dark:bg-purple-950/20 italic">
      <span className="shrink-0">{icon}</span>
      <span>{step.text}</span>
    </div>
  );
}

/** Build ThinkingStep array from turn state */
export function buildThinkingSteps(
  reasoning: string[],
  toolCalls: AgentToolCallPayload[],
  thinkingMessages: string[],
): ThinkingStep[] {
  // Interleave based on the order they were received
  // For now, show reasoning first, then tool calls with interleaved thinking
  const steps: ThinkingStep[] = [];
  for (const r of reasoning) {
    steps.push({ type: "reasoning", text: r });
  }
  // Tool calls and thinking messages interleaved by order
  let thinkIdx = 0;
  for (const tc of toolCalls) {
    // Check if there's a thinking message before this tool call
    if (thinkIdx < thinkingMessages.length) {
      steps.push({ type: "thinking", text: thinkingMessages[thinkIdx] });
      thinkIdx++;
    }
    steps.push({
      type: "tool_call",
      text: tc.tool,
      tool: tc.tool,
      latencyMs: tc.latency_ms,
      success: tc.success,
    });
  }
  // Remaining thinking messages
  while (thinkIdx < thinkingMessages.length) {
    steps.push({ type: "thinking", text: thinkingMessages[thinkIdx] });
    thinkIdx++;
  }
  return steps;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/components/ChatPane/ThinkingDrawer.tsx
git commit -m "feat(frontend): add ThinkingDrawer component with live/collapsed/expanded states"
```

---

### Task 6: Create CoursePanel router and StudentPanel

**Files:**
- Create: `src/frontend/components/CoursePanel/CoursePanel.tsx`
- Create: `src/frontend/components/CoursePanel/StudentPanel.tsx`
- Create: `src/frontend/components/CoursePanel/FacultyPanel.tsx`
- Create: `src/frontend/components/CoursePanel/AdvisorPanel.tsx`
- Create: `src/frontend/components/CoursePanel/AdminPanel.tsx`

- [ ] **Step 1: Create CoursePanel router**

```tsx
"use client";

import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import { StudentPanel } from "./StudentPanel";
import { FacultyPanel } from "./FacultyPanel";
import { AdvisorPanel } from "./AdvisorPanel";
import { AdminPanel } from "./AdminPanel";

export function CoursePanel() {
  const { persona, sessionId } = useSession();
  const { briefCardData } = useTurn();

  if (!sessionId) {
    return (
      <aside className="flex h-full flex-col items-center justify-center border-l border-border bg-muted/30 p-4">
        <p className="text-xs text-muted-foreground">Select a course to get started.</p>
      </aside>
    );
  }

  return (
    <aside className="flex h-full flex-col overflow-y-auto border-l border-border bg-muted/30 p-4">
      {persona === "student" && <StudentPanel data={briefCardData} />}
      {persona === "faculty" && <FacultyPanel data={briefCardData} />}
      {persona === "advisor" && <AdvisorPanel data={briefCardData} />}
      {persona === "admin" && <AdminPanel data={briefCardData} />}
    </aside>
  );
}
```

- [ ] **Step 2: Create StudentPanel**

```tsx
"use client";

import type { BriefCardPayload } from "@/lib/events";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

export function StudentPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading course data...</p>;
  }

  const progressPct = data.current_module.total > 0
    ? Math.round((data.current_module.index / data.current_module.total) * 100)
    : 0;

  return (
    <div className="space-y-4">
      {/* Course Progress */}
      {data.current_module.total > 0 && (
        <section>
          <SectionLabel>Course Progress</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="mb-1 flex justify-between text-xs text-muted-foreground">
              <span>Module {data.current_module.index} of {data.current_module.total}</span>
              <span>{data.current_module.title}</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted">
              <div className="h-1.5 rounded-full bg-primary transition-all" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        </section>
      )}

      {/* Performance */}
      {data.stats.total_assignments > 0 && (
        <section>
          <SectionLabel>Your Performance</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            <StatRow label="Avg Score" value={`${Math.round(data.stats.avg_score * 100)}%`} />
            <StatRow label="Submitted" value={`${data.stats.submissions_count}/${data.stats.total_assignments}`} />
            {data.assignments.length > 0 && (() => {
              const focus = data.assignments.reduce((a, b) =>
                (a.score ?? 1) < (b.score ?? 1) ? a : b
              );
              return focus.score !== null ? (
                <StatRow label="Focus Area" value={focus.title} valueClass="text-amber-600 dark:text-amber-400" />
              ) : null;
            })()}
          </div>
        </section>
      )}

      {/* Assignments */}
      {data.assignments.length > 0 && (
        <section>
          <SectionLabel>Assignments</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {data.assignments.map((a, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{a.title}</span>
                <span className={`shrink-0 font-mono ${
                  a.score !== null && a.score < 0.5 ? "text-destructive"
                    : a.score !== null ? "text-green-600 dark:text-green-400"
                    : "text-muted-foreground"
                }`}>
                  {a.score !== null ? `${Math.round(a.score * 100)}%` : "--"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Quick Actions */}
      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("What assignments do I have?")}>📋 My assignments</Pill>
          <Pill onClick={() => sendPrompt("What are my areas to focus on?")}>🎯 Growth areas</Pill>
          <Pill onClick={() => sendPrompt("Quiz me on the current module")}>📝 Quiz me</Pill>
          <Pill onClick={() => sendPrompt("Help me build a study plan")}>📚 Study plan</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function StatRow({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={valueClass ?? "font-medium"}>{value}</span>
    </div>
  );
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
```

- [ ] **Step 3: Create FacultyPanel**

```tsx
"use client";

import type { BriefCardPayload } from "@/lib/events";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

export function FacultyPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading course data...</p>;
  }

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Class at a Glance</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          <StatRow label="Students" value={`${data.stats.submissions_count}`} />
          {data.current_module.total > 0 && (
            <StatRow label="Modules" value={`${data.current_module.total}`} />
          )}
        </div>
      </section>

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("How is my class performing overall?")}>📊 Class performance</Pill>
          <Pill onClick={() => sendPrompt("Which students are at risk of falling behind?")}>⚠️ At-risk students</Pill>
          <Pill onClick={() => sendPrompt("Are there any submissions I need to grade?")}>📝 Grade submissions</Pill>
          <Pill onClick={() => sendPrompt("Help me create a quiz on the current module")}>🎯 Create quiz</Pill>
          <Pill onClick={() => sendPrompt("Draft an announcement for my class")}>📢 Announcement</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
```

- [ ] **Step 4: Create AdvisorPanel**

```tsx
"use client";

import type { BriefCardPayload } from "@/lib/events";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

export function AdvisorPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Caseload Overview</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          <StatRow label="Students" value={`${data.stats.submissions_count}`} />
        </div>
      </section>

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("Which students need attention in this course?")}>⚠️ At-risk students</Pill>
          <Pill onClick={() => sendPrompt("Show me engagement trends for this course")}>📈 Engagement trends</Pill>
          <Pill onClick={() => sendPrompt("Which students are behind on degree requirements?")}>🎓 Degree progress</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
```

- [ ] **Step 5: Create AdminPanel**

```tsx
"use client";

import type { BriefCardPayload } from "@/lib/events";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

export function AdminPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Platform Overview</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          <StatRow label="Enrolled" value={`${data.stats.submissions_count} persons`} />
        </div>
      </section>

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("Give me an overview of this course's health")}>🏥 Course health</Pill>
          <Pill onClick={() => sendPrompt("What are the enrollment numbers?")}>📊 Enrollment stats</Pill>
          <Pill onClick={() => sendPrompt("What's the status of the grading pipeline?")}>📝 Grading pipeline</Pill>
          <Pill onClick={() => sendPrompt("Are there any accessibility concerns?")}>♿ Accessibility audit</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
```

- [ ] **Step 6: Commit all panels**

```bash
git add src/frontend/components/CoursePanel/
git commit -m "feat(frontend): add CoursePanel router with Student/Faculty/Advisor/Admin panels"
```

---

### Task 7: Update ChatPane to render thinking inline

**Files:**
- Modify: `src/frontend/components/ChatPane/ChatPane.tsx`

- [ ] **Step 1: Add thinking drawer to ChatPane**

Import ThinkingDrawer and buildThinkingSteps. In the messages rendering, insert a ThinkingDrawer between the last user message and the assistant response. The key logic:

- While `turnState.status === "streaming"`, show ThinkingDrawer with `isStreaming={true}` after the last user message
- When `turnState.status === "done"`, the thinking drawer becomes collapsed (isStreaming={false})

Add to the ChatPane, before `<MessageList>`:

After the existing `useEffect` blocks and before `return`, add:

```tsx
  // Build thinking steps for the drawer
  const thinkingSteps = buildThinkingSteps(
    turnState.reasoning,
    turnState.toolCalls,
    turnState.thinkingMessages,
  );
```

Replace the `<MessageList messages={messages} />` with a custom renderer that interleaves thinking drawers:

```tsx
  // Build the display list: messages with thinking drawers inserted
  const displayItems: Array<{ type: "message"; msg: ChatMessage } | { type: "thinking"; steps: typeof thinkingSteps; streaming: boolean; tokens: number }> = [];

  for (const msg of messages) {
    displayItems.push({ type: "message", msg });
    // After a user message, if there's an active turn with thinking, insert the drawer
    if (msg.role === "user" && thinkingSteps.length > 0) {
      const isThisTurn = msg.id.includes(turnState.activeTurnId ?? "___");
      // For the most recent user message, show the thinking drawer
      if (msg === messages.filter(m => m.role === "user").pop()) {
        displayItems.push({
          type: "thinking",
          steps: thinkingSteps,
          streaming: turnState.status === "streaming",
          tokens: turnState.finalResult?.tokens ?? 0,
        });
      }
    }
  }
```

Then render:

```tsx
  <div className="flex-1 overflow-y-auto p-4 space-y-2">
    {displayItems.length === 0 && (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Start a conversation with the AI-First LMS.</p>
      </div>
    )}
    {displayItems.map((item, i) =>
      item.type === "message" ? (
        <MessageBubble key={item.msg.id} message={item.msg} />
      ) : (
        <ThinkingDrawer
          key={`thinking-${i}`}
          steps={item.steps}
          isStreaming={item.streaming}
          tokenCount={item.tokens}
          toolCallCount={item.steps.filter(s => s.type === "tool_call").length}
        />
      )
    )}
  </div>
```

Note: This replaces the `<MessageList>` component with inline rendering so we can interleave thinking drawers. Remove the MessageList import.

- [ ] **Step 2: Commit**

```bash
git add src/frontend/components/ChatPane/ChatPane.tsx
git commit -m "feat(frontend): render thinking steps inline in chat with collapsible drawer"
```

---

### Task 8: Rewire page layout — two columns, new header

**Files:**
- Modify: `src/frontend/app/page.tsx`

- [ ] **Step 1: Replace the three-column layout**

```tsx
"use client";

import { Header } from "@/components/Header/Header";
import { ChatPane } from "@/components/ChatPane/ChatPane";
import { CoursePanel } from "@/components/CoursePanel/CoursePanel";
import { TurnProvider } from "@/lib/turn-context";

export default function Home() {
  return (
    <TurnProvider>
      <div className="flex h-full flex-col">
        <Header />
        <div className="grid flex-1 grid-cols-[1fr_300px] overflow-hidden">
          <ChatPane />
          <CoursePanel />
        </div>
      </div>
    </TurnProvider>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/app/page.tsx
git commit -m "feat(frontend): two-column layout with Header + ChatPane + CoursePanel"
```

---

### Task 9: Build, deploy, and smoke test

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

- [ ] **Step 3: Test student flow**

Open http://localhost:3000, select Student + CS 101.
Expected:
- Header shows "AI-First LMS · CS 101 · Student"
- Right panel shows StudentPanel with progress, performance, assignments, quick actions
- Chat shows coaching message
- Thinking events show inline (if any)

- [ ] **Step 4: Test persona switching**

Switch to Faculty.
Expected:
- Header updates to Faculty
- Right panel shows FacultyPanel with class stats and quick actions
- Chat shows faculty coaching message

- [ ] **Step 5: Test thinking drawer**

Click a quick action pill (e.g., "Growth areas"). After response completes:
- Thinking drawer should be collapsed: "▶ Thinking · X tool calls"
- Click to expand and see full trace
- Response appears directly below the drawer

- [ ] **Step 6: Fix any issues and commit**
