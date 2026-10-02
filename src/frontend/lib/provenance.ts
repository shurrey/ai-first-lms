import type { AgentResultPayload, AgentToolCallPayload } from "./events";

/** Mirrors contracts/api.openapi.yaml provenance and measurement schemas. */
export type AiActionType =
  | "generation"
  | "grade_draft"
  | "criterion_feedback"
  | "practice_item"
  | "recommendation"
  | "attestation"
  | "profile_update"
  | "nudge"
  | "alert";

export type HumanDecisionValue =
  | "accepted"
  | "edited"
  | "rejected"
  | "overridden"
  | "dismissed"
  | "disputed"
  | "snoozed";

export interface ProvenanceSource {
  type: "content_item" | "node" | "submission" | "rubric" | "policy";
  id: string;
  version?: number | string | null;
  title?: string | null;
}

export interface AppliedPolicy {
  key: string;
  value: unknown;
  scope_type: "vendor_default" | "institution" | "program" | "course" | "learner";
  scope_id?: string | null;
  version?: number | null;
}

export interface HumanDecision {
  id: string;
  ai_action_id: string;
  decided_by: string;
  decided_by_name?: string | null;
  decision: HumanDecisionValue;
  diff?: Record<string, unknown> | null;
  reason?: string | null;
  decided_at: string;
}

export interface AiAction {
  id: string;
  session_id?: string | null;
  turn_id?: string | null;
  agent: string;
  action_type: AiActionType;
  subject_person_id?: string | null;
  course_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  sources: ProvenanceSource[];
  policies: AppliedPolicy[];
  model?: string | null;
  prompt_sha256?: string | null;
  output: Record<string, unknown>;
  created_at: string;
  decisions: HumanDecision[];
}

export interface DecisionRates {
  agent?: string | null;
  action_type?: AiActionType | null;
  total: number;
  accepted: number;
  edited: number;
  rejected: number;
  other?: number;
  undecided: number;
  acceptance_rate?: number | null;
  edit_rate?: number | null;
  reject_rate?: number | null;
}

export interface DeltaStat {
  n: number;
  mean_delta?: number | null;
}

export interface MeasurementSummary {
  scope: { type: "course" | "program" | "institution"; id?: string | null; title?: string | null };
  from: string | null;
  to: string;
  rates: DecisionRates[];
  criterion_score_changes: Array<{ criterion_id: string; criterion_key: string; n: number; mean_delta: number }>;
  learning_delta_by_decision: { accepted: DeltaStat; edited: DeltaStat; rejected: DeltaStat };
  most_edited_criteria: Array<{ criterion_id: string; criterion_key: string; edit_count: number; edit_rate: number }>;
  offloading?: { hint_dependency_ratio?: number | null; solution_check_trips?: number };
}

export interface MeasurementRollup extends MeasurementSummary {
  per_course: Array<{ course: { course_id: string; slug?: string | null; title: string }; totals: DecisionRates }>;
  compliance: { mismatches_count: number };
}

/** What a turn reported about how its answer was produced, for the label when no ai_action is linked. */
export interface TurnSources {
  agents: string[];
  tools: string[];
  citations: string[];
}

export const EMPTY_TURN_SOURCES: TurnSources = { agents: [], tools: [], citations: [] };

function citationLabel(c: unknown): string | null {
  if (typeof c === "string") return c.trim() || null;
  if (c && typeof c === "object") {
    const o = c as Record<string, unknown>;
    for (const k of ["title", "label", "name", "url", "id"]) {
      if (typeof o[k] === "string" && (o[k] as string).trim()) return (o[k] as string).trim();
    }
  }
  return null;
}

/** Agents and successful tools that ran, plus any `citations` the agents returned in their output. */
export function buildTurnSources(
  completedAgents: AgentResultPayload[],
  toolCalls: AgentToolCallPayload[],
): TurnSources {
  const agents = new Set<string>();
  const citations = new Set<string>();
  for (const r of completedAgents) {
    if (r.success) agents.add(r.agent);
    const raw = r.output?.citations;
    if (Array.isArray(raw)) {
      for (const c of raw) {
        const label = citationLabel(c);
        if (label) citations.add(label);
      }
    }
  }
  const tools = new Set(toolCalls.filter((t) => t.success).map((t) => t.tool));
  return { agents: [...agents], tools: [...tools], citations: [...citations] };
}

/** `ai_action_id` an artifact's data carries, if any. */
export function artifactAiActionId(data: Record<string, unknown>): string | null {
  const id = data.ai_action_id;
  return typeof id === "string" && id ? id : null;
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

/** 0–1 rate as a whole percent; "—" when the server reports no decided items. */
export function formatRate(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;
}

export function formatDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "—";
  const rounded = Math.round(delta * 100) / 100;
  return rounded > 0 ? `+${rounded}` : `${rounded}`;
}
