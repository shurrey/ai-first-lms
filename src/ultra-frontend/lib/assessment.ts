import type { Capabilities, FeedbackStatus, Role, TrajectoryFlag } from "./types";

export function humanizeKey(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Feedback states that can still change without the student acting. */
export function feedbackStillOpen(status: FeedbackStatus): boolean {
  return status === "pending" || status === "awaiting_release";
}

const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 30_000;

/** Delay before poll number `attempt` (0-based): doubles from 1.5 s, capped at 30 s. */
export function pollDelay(attempt: number): number {
  return Math.min(POLL_FIRST_MS * 2 ** attempt, POLL_MAX_MS);
}

export interface ChangeText {
  kind: "up" | "down" | "same" | "first" | "unknown";
  text: string;
}

export function describeDelta(delta: number | null | undefined, isFirst: boolean): ChangeText {
  if (isFirst) return { kind: "first", text: "First version" };
  if (delta == null) return { kind: "unknown", text: "No comparison" };
  if (delta > 0) return { kind: "up", text: `Up ${delta}` };
  if (delta < 0) return { kind: "down", text: `Down ${Math.abs(delta)}` };
  return { kind: "same", text: "No change" };
}

export const FLAG_LABELS: Record<TrajectoryFlag, string> = {
  improving: "Improving",
  plateaued: "Plateaued",
  regressed: "Regressed",
  ready_for_summative: "Ready for summative",
};

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Course tabs for the formative loop. Students submit; staff with release or commit rights review. */
export function showsAssignmentsTab(role: Role, caps: Capabilities): boolean {
  return role === "student" && !!caps.submit_work;
}

export function showsReviewQueueTab(caps: Capabilities): boolean {
  return !!caps.feedback_release || !!caps.grade_commit;
}

/**
 * GET /api/access-log is admin-only. /me has no dedicated capability, so this reads the admin row
 * of the §17 matrix: learner profiles of others at `all` scope, full access ("Logged").
 */
export function canReadAccessLog(caps: Capabilities): boolean {
  const grant = caps.learner_profile_of_others;
  return grant?.scope === "all" && grant.access === "full";
}

export const FEEDBACK_STATUS_TEXT: Record<FeedbackStatus, string> = {
  pending: "Feedback is being generated",
  awaiting_release: "Feedback is with your instructor for review",
  released: "Feedback available",
  suppressed: "Your instructor did not release feedback for this version",
  failed: "Feedback could not be generated for this version",
  none: "Final submitted for grading",
};

export interface PracticeItem {
  /** The stored question's id, when the generator recorded one. */
  question_id?: string;
  type?: string;
  stem: string;
  /** `value` is what an attempt sends: the option's key for keyed options, else its text. */
  options?: PracticeOption[];
}

export interface PracticeOption { value: string; label: string }

/** The practice_item output shape is not pinned by the contract; reads `items` or `questions`. */
export function practiceItems(output: Record<string, unknown>): PracticeItem[] {
  const raw = Array.isArray(output.items) ? output.items : Array.isArray(output.questions) ? output.questions : [];
  // content.generate_practice stores ids in a top-level `question_ids` array parallel to `items`.
  const ids = Array.isArray(output.question_ids) ? output.question_ids : [];
  return raw.flatMap((r, i): PracticeItem[] => {
    if (!r || typeof r !== "object") return [];
    const item = r as Record<string, unknown>;
    if (typeof item.stem !== "string") return [];
    const opts = item.options;
    const options = Array.isArray(opts)
      ? opts.map((o) => ({ value: String(o), label: String(o) }))
      : opts && typeof opts === "object" ? Object.entries(opts).map(([k, v]) => ({ value: k, label: `${k}. ${String(v)}` })) : undefined;
    return [{
      question_id: typeof item.question_id === "string" ? item.question_id
        : typeof ids[i] === "string" ? ids[i] as string : undefined,
      type: typeof item.type === "string" ? item.type : undefined,
      stem: item.stem,
      options,
    }];
  });
}
