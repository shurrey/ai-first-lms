import { humanizeKey } from "./assessment";
import type { CriterionFeedback, Submission, SubmissionFeedback } from "./types";

export interface CriterionEdit { score: string; rationale: string; next_step: string; suppress: boolean }

export function initialEdit(c: CriterionFeedback): CriterionEdit {
  return { score: c.ai_score == null ? "" : String(c.ai_score), rationale: c.ai_rationale ?? "", next_step: c.next_step ?? "", suppress: false };
}

/** Only changed fields are sent, so an unchanged criterion is recorded as `accepted`. */
export function releaseEdits(criteria: CriterionFeedback[], edits: Record<string, CriterionEdit>) {
  return criteria.flatMap((c) => {
    const e = edits[c.criterion_id];
    if (!e) return [];
    const out: { criterion_id: string; score?: number | null; rationale?: string | null; next_step?: string | null; suppress?: boolean } = { criterion_id: c.criterion_id };
    const score = e.score.trim() === "" ? null : Number(e.score);
    if (score !== (c.ai_score ?? null)) out.score = score;
    if (e.rationale !== (c.ai_rationale ?? "")) out.rationale = e.rationale;
    if (e.next_step !== (c.next_step ?? "")) out.next_step = e.next_step;
    if (e.suppress) out.suppress = true;
    return Object.keys(out).length > 1 ? [out] : [];
  });
}

export interface FinalToGrade { submission: Submission; feedback: SubmissionFeedback }

/** A final is committed once every criterion carries an instructor final_score. */
export function isCommitted(feedback: SubmissionFeedback): boolean {
  return feedback.criteria.length > 0 && feedback.criteria.every((c) => c.final_score != null);
}

/** Missing pieces that block a commit (spec §7.4): a final score on every criterion and a closing comment. */
export function commitProblems(criteria: CriterionFeedback[], scores: Record<string, string>, closing: string): string[] {
  const problems: string[] = [];
  if (criteria.length === 0) problems.push("No rubric criteria are scored yet. Ask the grading assistant for a draft first.");
  for (const c of criteria) {
    const v = scores[c.criterion_id]?.trim() ?? "";
    if (v === "" || !Number.isInteger(Number(v))) problems.push(`Enter a final score for ${humanizeKey(c.criterion_key)}.`);
  }
  if (!closing.trim()) problems.push("Write a closing comment.");
  return problems;
}

export function commitPrompt(item: FinalToGrade, scores: Record<string, string>, closing: string): string {
  const who = item.feedback.student_name ?? "this student";
  const lines = item.feedback.criteria.map((c) => `- ${c.criterion_key}: ${scores[c.criterion_id].trim()}`);
  return [
    `Commit the grade for ${who}'s final submission ${item.submission.id}.`,
    "Use exactly these instructor final scores:",
    ...lines,
    `Instructor closing comment: "${closing.trim()}"`,
    "Record them as the instructor's scores and closing comment, then commit the grade.",
  ].join("\n");
}
