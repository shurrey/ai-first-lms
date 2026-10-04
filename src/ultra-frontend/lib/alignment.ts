import { apiJson } from "./api";

export interface ProposalLevel { score: number; label: string; descriptor: string }
export interface OutcomeRef { node_id: string; title: string; reason?: string }

export interface ProposedCriterion {
  key: string;
  description: string;
  levels: ProposalLevel[];
  outcome_nodes: string[];
  rationale?: string;
}

/** Course Architect's `content_draft` of kind `alignment_proposal` (spec §7.6). */
export interface AlignmentProposal {
  assignment_node: string;
  title: string;
  outcomes: OutcomeRef[];
  criteria: ProposedCriterion[];
}

export type CriterionDecisionValue = "accept" | "edit" | "reject";

export interface CriterionBody {
  key: string;
  description: string;
  levels: ProposalLevel[];
  outcome_nodes: string[];
}

/** One entry per proposed criterion; `criterion` carries the edited version and is required for `edit`. */
export interface AlignmentDecision {
  key: string;
  decision: CriterionDecisionValue;
  criterion?: CriterionBody;
  reason?: string;
}

export interface AlignmentDecisionBody {
  /** Omitted: the server decides on the assignment's newest proposal. */
  ai_action_id?: string;
  decisions: AlignmentDecision[];
}

export interface AlignmentDecisionResult {
  ai_action_id: string;
  /** Null when every criterion was rejected and the rubric was left alone. */
  rubric_id: string | null;
  criterion_ids: string[];
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function levels(v: unknown): ProposalLevel[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((l): ProposalLevel[] => {
    const o = (l ?? {}) as Record<string, unknown>;
    return typeof o.score === "number" ? [{ score: o.score, label: str(o.label) ?? "", descriptor: str(o.descriptor) ?? "" }] : [];
  });
}

/** Reads an artifact from a `final` event; null unless it is an alignment proposal with an assignment. */
export function parseAlignmentProposal(artifact: unknown): AlignmentProposal | null {
  const a = (artifact ?? {}) as { type?: unknown; data?: Record<string, unknown> };
  const data = a.data ?? {};
  if (a.type !== "content_draft" || data.kind !== "alignment_proposal") return null;
  const node = str(data.assignment_node);
  if (!node) return null;
  const outcomes = (Array.isArray(data.outcomes) ? data.outcomes : []).flatMap((o): OutcomeRef[] => {
    const r = (o ?? {}) as Record<string, unknown>;
    const id = str(r.node_id);
    return id ? [{ node_id: id, title: str(r.title) ?? id, reason: str(r.reason) ?? undefined }] : [];
  });
  const criteria = (Array.isArray(data.criteria) ? data.criteria : []).flatMap((c): ProposedCriterion[] => {
    const r = (c ?? {}) as Record<string, unknown>;
    const key = str(r.key);
    if (!key) return [];
    const nodes = Array.isArray(r.outcome_nodes)
      ? r.outcome_nodes.flatMap((n) => (typeof n === "string" ? [n] : str((n as Record<string, unknown>)?.node_id) ?? []))
      : [];
    return [{ key, description: str(r.description) ?? "", levels: levels(r.levels), outcome_nodes: nodes, rationale: str(r.rationale) ?? undefined }];
  });
  return { assignment_node: node, title: str(data.title) ?? "Alignment proposal", outcomes, criteria };
}

export function alignmentDecisionsPath(assignmentNode: string): string {
  return `/api/assignments/${encodeURIComponent(assignmentNode)}/alignment/decisions`;
}

/** Records one human decision per proposed criterion; accepted and edited criteria are saved to the rubric. */
export function submitAlignmentDecisions(assignmentNode: string, body: AlignmentDecisionBody): Promise<AlignmentDecisionResult> {
  return apiJson<AlignmentDecisionResult>(alignmentDecisionsPath(assignmentNode), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    reportForbidden: false,
  });
}

export function alignmentPrompt(assignmentNode: string): string {
  return `Propose the outcome alignment and rubric criteria for assignment_node ${assignmentNode}.`;
}
