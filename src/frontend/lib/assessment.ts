import { apiJson } from "./api";
import type { AiAction, HumanDecision } from "./provenance";

/** Mirrors contracts/api.openapi.yaml assessment schemas (Submission, SubmissionFeedback, Improvement). */
export type SubmissionStatus = "draft" | "final";
export type FeedbackStatus = "pending" | "awaiting_release" | "released" | "suppressed" | "failed" | "none";
export type ReleaseMode = "auto" | "instructor_release";

export interface Submission {
  id: string;
  person_id: string;
  assignment_id: string;
  course_id?: string | null;
  version: number;
  parent_id?: string | null;
  status: SubmissionStatus;
  body_md?: string | null;
  submitted_at: string;
  feedback_status?: FeedbackStatus;
  assignment_title?: string | null;
}

export interface EvidenceSpan {
  quote: string;
  start?: number | null;
  end?: number | null;
}

export interface CriterionFeedback {
  criterion_id: string;
  criterion_key: string;
  description: string;
  ai_score: number | null;
  level_label?: string | null;
  ai_rationale?: string | null;
  evidence_spans: EvidenceSpan[];
  next_step?: string | null;
  final_score?: number | null;
  ai_action_id?: string | null;
  released_at?: string | null;
}

export interface SubmissionFeedback {
  submission_id: string;
  assignment_id?: string;
  person_id?: string;
  student_name?: string | null;
  status: FeedbackStatus;
  release_mode: ReleaseMode;
  criteria: CriterionFeedback[];
  practice_set_ai_action_id?: string | null;
}

export interface SubmissionHistory {
  assignment_id: string;
  person_id: string;
  versions: Array<{
    submission: Submission;
    criteria: Array<{ criterion_id: string; criterion_key: string; score: number | null; delta: number | null }>;
  }>;
}

export type TrajectoryFlag = "improving" | "plateaued" | "regressed" | "ready_for_summative";

export interface TrajectoryPoint {
  submission_id: string;
  version: number;
  status: SubmissionStatus;
  score: number | null;
  submitted_at: string;
}

export interface CriterionTrajectory {
  criterion_id: string;
  points: TrajectoryPoint[];
  latest_delta?: number | null;
  flag: TrajectoryFlag | null;
}

export interface Improvement {
  course_id: string;
  criteria: Array<{ criterion_id: string; criterion_key: string; description: string; target_score?: number | null }>;
  students: Array<{ student_id: string; display_name: string; trajectories: CriterionTrajectory[] }>;
  aggregate?: Array<{
    criterion_id: string;
    n_students: number;
    mean_delta?: number | null;
    flag_counts: Record<string, number>;
  }>;
}

export const FLAG_LABELS: Record<TrajectoryFlag, string> = {
  improving: "Improving",
  plateaued: "Plateaued",
  regressed: "Regressed",
  ready_for_summative: "Ready for summative",
};

export interface CriterionEdit {
  criterion_id: string;
  score?: number | null;
  rationale?: string | null;
  next_step?: string | null;
  suppress?: boolean;
}

/** POST /api/feedback/{id}/release; the request itself is the instructor's approval. */
export function releaseFeedback(
  submissionId: string,
  body: { action: "release" | "suppress"; edits?: CriterionEdit[]; reason?: string | null }
): Promise<SubmissionFeedback> {
  return apiJson(`/api/feedback/${encodeURIComponent(submissionId)}/release`, {
    method: "POST",
    json: body,
  });
}

/** POST /api/feedback/{id}/retry: starts another run for feedback whose generation failed. */
export function retryFeedback(submissionId: string): Promise<SubmissionFeedback> {
  return apiJson(`/api/feedback/${encodeURIComponent(submissionId)}/retry`, { method: "POST" });
}

/** POST /api/ai-actions/{id}/decisions (practice items: Start = accepted, Not helpful = dismissed). */
export function recordDecision(
  aiActionId: string,
  decision: "accepted" | "dismissed"
): Promise<HumanDecision> {
  return apiJson(`/api/ai-actions/${encodeURIComponent(aiActionId)}/decisions`, {
    method: "POST",
    json: { decision },
  });
}

/** `correct` is null for items that are not scored automatically (short answer, essay, code). */
export interface PracticeItemResult {
  question_id: string;
  correct: boolean | null;
  /** The contract sends a display string (or null); a raw answer_key object is also understood. */
  expected?: unknown;
  feedback?: string | null;
}

export interface PracticeAttemptResult {
  practice_set_id: string;
  attempt_id: string | null;
  correct: number;
  total: number;
  results: PracticeItemResult[];
}

/** POST /api/practice/{id}/attempts: records a private attempt (spec §12.5) and marks it. */
export function submitPracticeAttempt(
  practiceSetId: string,
  answers: Array<{ question_id: string; answer: string }>
): Promise<PracticeAttemptResult> {
  return apiJson(`/api/practice/${encodeURIComponent(practiceSetId)}/attempts`, { method: "POST", json: { answers } });
}

export function itemResultText(r: PracticeItemResult, options: PracticeOption[] = []): string {
  const head =
    r.correct === true ? "Correct." : r.correct === false ? "Not quite." : "Answer recorded. This item isn't scored automatically.";
  const parts = [head];
  const label = (v: string) => options.find((o) => o.value.toLowerCase() === v.toLowerCase())?.label ?? v;
  const key = r.expected && typeof r.expected === "object" && !Array.isArray(r.expected) ? (r.expected as Record<string, unknown>) : null;
  const correct = key ? key.correct : r.expected;
  const answer =
    (typeof correct === "string" || typeof correct === "number" ? label(String(correct)) : null) ??
    (Array.isArray(correct) ? correct.map((c) => label(String(c))).join(" or ") : null) ??
    (key && Array.isArray(key.model_points) ? key.model_points.filter((p) => typeof p === "string").join("; ") : null);
  if (r.correct !== true && answer) parts.push(`${r.correct === null ? "Model answer" : "Expected"}: ${answer.replace(/\.$/, "")}.`);
  const explanation = key ? str(key.explanation) : null;
  if (explanation) parts.push(explanation);
  if (r.feedback) parts.push(r.feedback);
  return parts.join(" ");
}

export type AlignmentDecisionValue = "accept" | "edit" | "reject";

export interface AlignmentDecision {
  key: string;
  decision: AlignmentDecisionValue;
  /** The edited criterion; required for `edit`. */
  criterion?: { key: string; description: string; levels: Array<{ score: number; label: string; descriptor: string }>; outcome_nodes: string[] };
  reason?: string;
}

export interface AlignmentDecisionResult {
  ai_action_id: string;
  /** Null when every criterion was rejected and the rubric was left alone. */
  rubric_id: string | null;
  criterion_ids: string[];
}

/** POST /api/assignments/{node}/alignment/decisions: one decision per proposed criterion, faculty of the course only. */
export function submitAlignmentDecisions(
  assignmentNode: string,
  decisions: AlignmentDecision[]
): Promise<AlignmentDecisionResult> {
  return apiJson(`/api/assignments/${encodeURIComponent(assignmentNode)}/alignment/decisions`, {
    method: "POST",
    json: { decisions },
  });
}

export interface PracticeItem {
  id: string;
  /** The stored question's id; null when the set's output names none, so it can't be attempted. */
  question_id: string | null;
  type: string;
  stem: string;
  options: PracticeOption[];
  answer: string | null;
  bloom_level: string | null;
}

export interface PracticeSet {
  ai_action_id: string;
  title: string;
  created_at: string;
  items: PracticeItem[];
  decided: boolean;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

/** `value` is what an attempt sends: the option's key for keyed options, else its text. */
export interface PracticeOption {
  value: string;
  label: string;
}

function optionList(v: unknown): PracticeOption[] {
  if (Array.isArray(v)) {
    return v.map((o) => {
      const t = typeof o === "string" ? o : str((o as { text?: unknown })?.text) ?? JSON.stringify(o);
      return { value: t, label: t };
    });
  }
  if (v && typeof v === "object") return Object.entries(v).map(([k, t]) => ({ value: k, label: `${k}. ${String(t)}` }));
  return [];
}

function answerText(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === "string" || typeof v === "number") return String(v);
  const o = v as Record<string, unknown>;
  const points = Array.isArray(o.model_points) ? o.model_points.filter((p) => typeof p === "string").join("; ") : null;
  const main = str(o.answer) ?? str(o.text) ?? str(o.correct) ?? str(points);
  const explanation = str(o.explanation);
  if (main && explanation) return `${main}. ${explanation}`;
  return main ?? explanation ?? JSON.stringify(v);
}

/**
 * Reads a practice_item ai_action's output, which holds either an `items`/`questions` list
 * or a single item. Shapes vary by agent version, so unknown fields are ignored.
 */
export function toPracticeSet(action: AiAction): PracticeSet {
  const out = action.output ?? {};
  const raw = Array.isArray(out.items) ? out.items : Array.isArray(out.questions) ? out.questions : str(out.stem) ? [out] : [];
  // content.generate_practice stores ids in a top-level `question_ids` array parallel to `items`.
  const ids = Array.isArray(out.question_ids) ? out.question_ids : [];
  const items = raw
    .map((r, i): PracticeItem | null => {
      const o = (r ?? {}) as Record<string, unknown>;
      const stem = str(o.stem) ?? str(o.question);
      if (!stem) return null;
      const questionId = str(o.question_id) ?? str(ids[i]);
      return {
        id: questionId ?? str(o.id) ?? `${action.id}-${i}`,
        question_id: questionId,
        type: str(o.type) ?? "short_answer",
        stem,
        options: optionList(o.options),
        answer: answerText(o.answer_key ?? o.answer),
        bloom_level: str(o.bloom_level),
      };
    })
    .filter((x): x is PracticeItem => x !== null);
  const criterion = str(out.criterion_key) ?? str(out.criterion);
  return {
    ai_action_id: action.id,
    title: str(out.title) ?? (criterion ? `Practice: ${criterion.replace(/_/g, " ")}` : "Practice set"),
    created_at: action.created_at,
    items,
    decided: action.decisions.length > 0,
  };
}

/** Releasable means faculty can still act on it; `auto` courses release without a person. */
export function isAwaitingRelease(f: SubmissionFeedback): boolean {
  return f.status === "awaiting_release" && f.release_mode === "instructor_release";
}

/** An access-log entry (GET /api/access-log) flattened for display. */
export interface AccessLogRow {
  id: string;
  actor_name: string;
  actor_role: string | null;
  resource: string;
  resource_id: string | null;
  purpose: string | null;
  created_at: string;
}

export const ACCESS_LOG_RESOURCES = ["transcript", "profile", "analyst_summary", "submission"] as const;

export function toAccessLogRow(raw: Record<string, unknown>, i: number): AccessLogRow {
  const actor = (raw.actor ?? {}) as Record<string, unknown>;
  return {
    id: str(raw.id) ?? `row-${i}`,
    actor_name: str(actor.display_name) ?? str(raw.actor_name) ?? str(actor.id) ?? str(raw.actor_id) ?? "Unknown",
    actor_role: str(actor.role) ?? str(raw.actor_role),
    resource: str(raw.resource) ?? "unknown",
    resource_id: str(raw.resource_id),
    purpose: str(raw.purpose),
    created_at: str(raw.created_at) ?? "",
  };
}
