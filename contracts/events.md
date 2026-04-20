# Events Contract

The SSE event envelope and every event type the orchestrator emits to the frontend. This file is a CONTRACT — do not edit without an approved `T-C-*` contract-change task.

---

## Envelope

Every event, regardless of type, conforms to this shape:

```typescript
interface EventEnvelope<P = unknown> {
  event:      EventType;     // one of the types below
  session_id: string;        // stable per session
  turn_id:    string;        // stable per user turn
  sequence:   number;        // monotonic per (session_id, turn_id), starting at 1
  timestamp:  string;        // ISO 8601 with ms
  payload:    P;             // shape depends on event type
}
```

Ordering guarantee: events with lower `sequence` always precede events with higher `sequence` within the same turn. Clients MUST reorder if they receive out-of-order.

---

## Event types

### `reasoning`

Emitted whenever the orchestrator's internal reasoning progresses a step.

```typescript
interface ReasoningPayload {
  step: "interpret" | "clarify" | "plan" | "dispatch" | "synthesize";
  text: string;               // human-readable narrative of what the orchestrator is doing
}
```

### `plan`

Emitted after planning; shows the full plan the orchestrator will execute.

```typescript
interface PlanPayload {
  strategy: "react" | "plan_then_execute";
  steps: Array<{
    step_id: string;
    agent: string;            // agent name from manifest
    input_summary: string;    // human-readable
    depends_on: string[];     // step_ids
  }>;
  estimated_cost_usd: number;
  estimated_tokens: number;
}
```

### `agent_start`

Emitted when a sub-agent begins execution.

```typescript
interface AgentStartPayload {
  step_id: string;
  agent: string;
  inputs: object;             // structured agent input
}
```

### `agent_token`

Emitted for each streamed token from a sub-agent. Frontend buffers and renders incrementally.

```typescript
interface AgentTokenPayload {
  step_id: string;
  agent: string;
  delta: string;              // token(s) to append
  channel: "thought" | "response";
}
```

### `agent_tool_call`

Emitted when a sub-agent invokes an MCP tool.

```typescript
interface AgentToolCallPayload {
  step_id: string;
  agent: string;
  tool: string;               // "content.retrieve", etc.
  arguments: object;
  result_summary: string;     // brief; do not include large payloads
  latency_ms: number;
  success: boolean;
}
```

### `agent_result`

Emitted when a sub-agent completes its step.

```typescript
interface AgentResultPayload {
  step_id: string;
  agent: string;
  output: object;             // structured output per agent manifest
  cost_usd: number;
  tokens: number;
  success: boolean;
}
```

### `clarify`

Orchestrator needs more information from the user before it can proceed. The turn pauses until the UI sends a follow-up message.

```typescript
interface ClarifyPayload {
  question: string;
  reason: string;             // why the orchestrator is asking
  options?: string[];         // optional multiple-choice hints
}
```

### `approval_request`

A step requires human approval before committing. The turn pauses until `POST /api/approval` is received.

```typescript
interface ApprovalRequestPayload {
  approval_id: string;
  step_id: string;
  agent: string;
  action: string;             // human-readable ("Commit grades for 23 students")
  preview: object;            // the drafted artifact (rubric, message, etc.)
  artifact_type: "rubric_grades" | "message" | "quiz" | "content_draft" | "other";
}
```

### `final`

The turn is complete. The orchestrator's final answer and any artifacts.

```typescript
interface FinalPayload {
  answer_markdown: string;
  artifacts: Array<{
    artifact_id: string;
    type: "rubric_grades" | "message" | "quiz" | "chart" | "degree_audit"
        | "content_draft" | "wcag_report" | "risk_list" | "learning_path";
    data: object;             // shape depends on type
  }>;
  cost_usd: number;
  tokens: number;
  wall_time_ms: number;
}
```

### `error`

Something went wrong. The turn ends.

```typescript
interface ErrorPayload {
  code: "budget_exceeded" | "permission_denied" | "agent_failure"
      | "mcp_failure" | "llm_failure" | "timeout" | "internal";
  message: string;            // user-safe
  retriable: boolean;
  step_id?: string;
}
```

---

## Example event sequence (scenario 5: draft announcement)

```
{event:"reasoning", sequence:1, payload:{step:"interpret", text:"Faculty wants to draft a midterm announcement."}}
{event:"plan",      sequence:2, payload:{strategy:"react", steps:[{step_id:"s1", agent:"communication", ...}]}}
{event:"agent_start", sequence:3, payload:{step_id:"s1", agent:"communication", inputs:{...}}}
{event:"agent_tool_call", sequence:4, payload:{step_id:"s1", agent:"communication", tool:"roster.get", ...}}
{event:"agent_tool_call", sequence:5, payload:{step_id:"s1", agent:"communication", tool:"templates.list", ...}}
{event:"agent_token", sequence:6-50, payload:{step_id:"s1", delta:"...", channel:"response"}}
{event:"agent_result", sequence:51, payload:{step_id:"s1", output:{draft: "..."}, ...}}
{event:"approval_request", sequence:52, payload:{approval_id:"a1", action:"Send announcement to 50 recipients", preview:{...}}}
# --- orchestrator waits for POST /api/approval ---
{event:"reasoning", sequence:53, payload:{step:"synthesize", text:"Approved; sending."}}
{event:"agent_tool_call", sequence:54, payload:{step_id:"s1", tool:"messages.send", ...}}
{event:"final", sequence:55, payload:{answer_markdown:"Announcement sent to 50 recipients.", artifacts:[...]}}
```
