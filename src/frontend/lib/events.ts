import { z } from "zod";

// --- Event type enum ---
export const EventType = z.enum([
  "reasoning",
  "plan",
  "agent_start",
  "agent_token",
  "agent_tool_call",
  "agent_result",
  "clarify",
  "approval_request",
  "final",
  "error",
]);
export type EventType = z.infer<typeof EventType>;

// --- Payload schemas ---

export const ReasoningPayload = z.object({
  step: z.enum(["interpret", "clarify", "plan", "dispatch", "synthesize"]),
  text: z.string(),
});

export const PlanStep = z.object({
  step_id: z.string(),
  agent: z.string(),
  input_summary: z.string(),
  depends_on: z.array(z.string()),
});

export const PlanPayload = z.object({
  strategy: z.enum(["react", "plan_then_execute"]),
  steps: z.array(PlanStep),
  estimated_cost_usd: z.number(),
  estimated_tokens: z.number(),
});

export const AgentStartPayload = z.object({
  step_id: z.string(),
  agent: z.string(),
  inputs: z.record(z.string(), z.unknown()),
});

export const AgentTokenPayload = z.object({
  step_id: z.string(),
  agent: z.string(),
  delta: z.string(),
  channel: z.enum(["thought", "response"]),
});

export const AgentToolCallPayload = z.object({
  step_id: z.string(),
  agent: z.string(),
  tool: z.string(),
  arguments: z.record(z.string(), z.unknown()),
  result_summary: z.string(),
  latency_ms: z.number(),
  success: z.boolean(),
});

export const AgentResultPayload = z.object({
  step_id: z.string(),
  agent: z.string(),
  output: z.record(z.string(), z.unknown()),
  cost_usd: z.number(),
  tokens: z.number(),
  success: z.boolean(),
});

export const ClarifyPayload = z.object({
  question: z.string(),
  reason: z.string(),
  options: z.array(z.string()).optional(),
});

export const ApprovalRequestPayload = z.object({
  approval_id: z.string(),
  step_id: z.string(),
  agent: z.string(),
  action: z.string(),
  preview: z.record(z.string(), z.unknown()),
  artifact_type: z.enum([
    "rubric_grades",
    "message",
    "quiz",
    "content_draft",
    "other",
  ]),
});

export const Artifact = z.object({
  artifact_id: z.string(),
  type: z.enum([
    "rubric_grades",
    "message",
    "quiz",
    "chart",
    "degree_audit",
    "content_draft",
    "wcag_report",
    "risk_list",
    "learning_path",
  ]),
  data: z.record(z.string(), z.unknown()),
});

export const FinalPayload = z.object({
  answer_markdown: z.string(),
  artifacts: z.array(Artifact),
  cost_usd: z.number(),
  tokens: z.number(),
  wall_time_ms: z.number(),
});

export const ErrorPayload = z.object({
  code: z.enum([
    "budget_exceeded",
    "permission_denied",
    "agent_failure",
    "mcp_failure",
    "llm_failure",
    "timeout",
    "internal",
  ]),
  message: z.string(),
  retriable: z.boolean(),
  step_id: z.string().optional(),
});

// --- Envelope ---

export const EventEnvelope = z.object({
  event: EventType,
  session_id: z.string(),
  turn_id: z.string(),
  sequence: z.number().int().positive(),
  timestamp: z.string(),
  payload: z.unknown(),
});

export type EventEnvelope = z.infer<typeof EventEnvelope>;

// --- Typed event helpers ---

const PAYLOAD_SCHEMAS: Record<string, z.ZodType> = {
  reasoning: ReasoningPayload,
  plan: PlanPayload,
  agent_start: AgentStartPayload,
  agent_token: AgentTokenPayload,
  agent_tool_call: AgentToolCallPayload,
  agent_result: AgentResultPayload,
  clarify: ClarifyPayload,
  approval_request: ApprovalRequestPayload,
  final: FinalPayload,
  error: ErrorPayload,
};

export function parseEvent(raw: unknown): EventEnvelope {
  const envelope = EventEnvelope.parse(raw);
  const payloadSchema = PAYLOAD_SCHEMAS[envelope.event];
  if (payloadSchema) {
    envelope.payload = payloadSchema.parse(envelope.payload);
  }
  return envelope;
}

// Typed payload accessors
export type ReasoningPayload = z.infer<typeof ReasoningPayload>;
export type PlanPayload = z.infer<typeof PlanPayload>;
export type AgentStartPayload = z.infer<typeof AgentStartPayload>;
export type AgentTokenPayload = z.infer<typeof AgentTokenPayload>;
export type AgentToolCallPayload = z.infer<typeof AgentToolCallPayload>;
export type AgentResultPayload = z.infer<typeof AgentResultPayload>;
export type ClarifyPayload = z.infer<typeof ClarifyPayload>;
export type ApprovalRequestPayload = z.infer<typeof ApprovalRequestPayload>;
export type FinalPayload = z.infer<typeof FinalPayload>;
export type ErrorPayload = z.infer<typeof ErrorPayload>;
