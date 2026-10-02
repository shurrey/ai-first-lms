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

```typescript
type EventType =
  | "reasoning" | "plan" | "agent_start" | "agent_token" | "agent_tool_call"
  | "agent_result" | "clarify" | "approval_request" | "final" | "error"
  // Round 2 — Status: planned (see each type below)
  | "guardrail" | "policy_context" | "feedback_ready" | "notification" | "session_ended";
```

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
  artifact_type: "rubric_grades" | "message" | "quiz" | "content_draft" | "other"
      // Round 2 (spec.md §5.3): live from T-E-107 for served tools; see the table below
      | "grade_commit" | "credential" | "attestation_override"
      | "policy_change" | "content_publish" | "feedback_release";
}
```

`artifact_type` for each write-gated tool in spec.md §5.3:

| Tool | `artifact_type` | Status |
|---|---|---|
| `assessments.commit_grade` | `grade_commit` | live (T-E-107) |
| `assessments.approve_credential` | `credential` | live (T-E-107) |
| `assessments.create_question` (publishing to a live bank) | `quiz` | existing value |
| `attestations.override` | `attestation_override` | planned (T-E-107, T-D-112) |
| `communications.send_message` | `message` | existing value |
| `content.publish` | `content_publish` | planned (T-E-107) |
| `feedback.release` (under `feedback.release_mode = instructor_release`) | `feedback_release` | planned (T-E-107, T-E-116) |
| `policy.set` | `policy_change` | planned (T-E-107, T-E-116) |

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
  ai_action_ids: string[];    // ids of the ai_actions rows written during this turn; [] if none
  cost_usd: number;
  tokens: number;
  wall_time_ms: number;
}
```

`ai_action_ids` lets a client link the turn's generated items to their provenance
(`GET /api/ai-actions/{id}`). It lists each row once, in the order written, including rows
for actions a person declined at approval. (Change: T-C-115.)

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

`budget_exceeded` is emitted by the tool gateway's budget step (spec.md §5.2 step 6) when a per-turn or per-session cap is hit; the turn hard-stops.

---

## Round 2 event types

The types below are added by T-C-103 (spec.md §18). Each is **Status: planned** until the named task ships it.

Delivery: like every event, these travel on a turn's SSE stream and carry that turn's `session_id`, `turn_id` and `sequence`. `notification`, `feedback_ready` and `session_ended` can originate outside any turn the recipient is streaming (scheduler jobs, another user's approval); in that case they are not pushed, and the client reads the same state through REST (`GET /api/notifications`, `/api/feedback/*`, `/api/sessions/{id}`, per T-C-102).

### `guardrail`

**Status:** `denied_permission`, `denied_scope`: live (T-E-106, spec.md §5.2 steps 1–3). `denied_policy`: planned, T-E-116 (§5.2 step 4, §8.4). `offload_check`: planned, T-E-118 (§13.2).

Emitted when the tool gateway refuses a tool call, or when the tutor offload post-check replaces a reply. It does **not** end the turn: a denied tool call returns a "not permitted" tool error to the model and the agent continues. A turn-ending authorization failure is `error{code:"permission_denied"}` instead.

| `kind` | Emitted by |
|---|---|
| `denied_permission` | Gateway step 1 (tool not in the agent's manifest `tools`) or step 2 (`active_role` not in the tool's `allowed_roles`) |
| `denied_scope` | Gateway step 3 (`ScopeDenied` from the §4.5 identity and scope rules) |
| `denied_policy` | Gateway step 4 (`policy.check_tool` refused, e.g. `ai.allowed_agents`) |
| `offload_check` | `tutor_offload_check` post-processor: the regenerated reply still contained a full solution, so it was replaced with a hint-level reply |

```typescript
interface GuardrailPayload {
  kind: "denied_permission" | "denied_scope" | "denied_policy" | "offload_check";
  step_id: string;
  agent: string;
  tool?: string;              // absent for offload_check
  reason: string;             // user-safe; never contains other students' names or raw arguments
  policy?: {                  // present for denied_policy; for offload_check, the tutor.answer_mode in effect
    key: string;              // policy registry key, e.g. "ai.allowed_agents"
    value: unknown;           // resolved value that caused the decision
    scope_type: "vendor_default" | "institution" | "program" | "course" | "learner";
    scope_id: string | null;  // null for vendor_default and institution
    version: number;
  };
  assignment_id?: string;     // offload_check only: the open assignment the session is linked to
}
```

The `kind` values match `tool_calls.outcome` (spec.md §6.3) so the compliance report (§8.7) can join gateway events to provenance rows.

### `policy_context`

**Status: planned** — T-E-115 (spec.md §8.5).

Emitted once per agent invocation, after `agent_start` and before the agent's first `agent_tool_call`. Lists exactly the resolved prompt-enforced keys placed in that invocation's `<policy_context>` block, with their sources.

```typescript
interface PolicyContextPayload {
  step_id: string;
  agent: string;
  policies: Array<{
    key: string;              // policy registry key, e.g. "tutor.answer_mode"
    value: unknown;           // resolved value; shape per the key's registry schema
    scope_type: "vendor_default" | "institution" | "program" | "course" | "learner";
    scope_id: string | null;  // null for vendor_default and institution
    version: number;          // policy_settings.version of the winning row
    locked: boolean;          // true if the value came from a locked higher scope
    conflict?: boolean;       // true if programs disagreed and the most restrictive value won
  }>;
}
```

### `feedback_ready`

**Status: planned** — T-E-116 (spec.md §7.3, §8.4 `feedback.release_mode`); consumed by T-F-106.

Emitted when criterion-level formative feedback on a submission becomes visible to the student: immediately after the feedback agent saves it under `auto`, or when faculty release it under `instructor_release`.

```typescript
interface FeedbackReadyPayload {
  submission_id: string;
  criteria_count: number;     // criteria with released feedback on this submission
  release_mode: "auto" | "instructor_release";
  released_at: string;        // ISO 8601; equals criterion_scores.released_at
}
```

### `notification`

**Status: planned** — T-E-121 (spec.md §10.4); consumed by T-F-113.

Emitted when a row is inserted into `notifications` for the person streaming. Jobs apply `nudges.enabled` and `nudges.quiet_hours` before inserting, so none is emitted during the recipient's quiet hours.

```typescript
interface NotificationPayload {
  id: string;
  person_id: string;          // always the authenticated recipient
  kind: string;               // e.g. "review_due" | "deadline" | "stalled_student" | "alert"
  title: string;
  body: string;
  link: string | null;        // in-app route
  ai_action_id: string | null;
  created_at: string;         // ISO 8601
  read_at: string | null;
  dismissed_at: string | null;
}
```

### `session_ended`

**Status: planned** — T-E-120 (spec.md §10.1).

Emitted when a session closes, either from the **End session** button or the `idle_session_closer` job. It is the last event for the session.

```typescript
interface SessionEndedPayload {
  reason: "user_ended" | "idle_timeout";
  reflection: {
    mode: "off" | "optional" | "required";   // resolved reflection.after_session
    status: "not_requested" | "submitted" | "skipped" | "pending";
    evidence_id?: string;     // present when status is "submitted"
  };
  ended_at: string;           // ISO 8601
}
```

`status` is `not_requested` when `mode` is `off`, and `pending` only for an `idle_timeout` close while a required reflection is outstanding.

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

## Example event sequence (scenario: offload check under a locked answer mode) — Status: planned

Institution has locked `tutor.answer_mode = socratic_only`; Emma asks the tutor for the answer to an open assignment.

```
{event:"reasoning",      sequence:1, payload:{step:"interpret", text:"Student wants help with Assignment 3."}}
{event:"plan",           sequence:2, payload:{strategy:"react", steps:[{step_id:"s1", agent:"tutor", ...}]}}
{event:"agent_start",    sequence:3, payload:{step_id:"s1", agent:"tutor", inputs:{...}}}
{event:"policy_context", sequence:4, payload:{step_id:"s1", agent:"tutor", policies:[{key:"tutor.answer_mode", value:"socratic_only", scope_type:"institution", scope_id:null, version:2, locked:true}]}}
{event:"agent_tool_call", sequence:5, payload:{step_id:"s1", agent:"tutor", tool:"content.retrieve", ...}}
# --- first draft leaked a solution; regenerated once; regenerated reply also failed ---
{event:"guardrail",      sequence:6, payload:{kind:"offload_check", step_id:"s1", agent:"tutor", reason:"Reply replaced with a hint because the assignment is still open.", policy:{key:"tutor.answer_mode", value:"socratic_only", scope_type:"institution", scope_id:null, version:2}, assignment_id:"..."}}
{event:"agent_result",   sequence:7, payload:{step_id:"s1", agent:"tutor", output:{...}, ...}}
{event:"final",          sequence:8, payload:{answer_markdown:"What do you think the first step is?", artifacts:[]}}
```
