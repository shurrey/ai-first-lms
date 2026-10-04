import { apiJson } from "./api";
import type { PracticeOption } from "./assessment";

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

/** Records a private practice attempt (spec §12.5); answers are keyed by the stored question's id. */
export function submitPracticeAttempt(
  practiceSetId: string, answers: { question_id: string; answer: string }[],
): Promise<PracticeAttemptResult> {
  return apiJson<PracticeAttemptResult>(`/api/practice/${encodeURIComponent(practiceSetId)}/attempts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
    reportForbidden: false,
  });
}

function text(v: unknown): string | null {
  if (typeof v === "string") return v.trim() || null;
  if (typeof v === "number") return String(v);
  return null;
}

/** The answer key as a sentence fragment; a keyed option's value is shown with its label. */
export function expectedText(expected: unknown, options: PracticeOption[] = []): { answer: string | null; explanation: string | null } {
  const label = (v: string) => options.find((o) => o.value.toLowerCase() === v.toLowerCase())?.label ?? v;
  const direct = text(expected);
  if (direct) return { answer: label(direct), explanation: null };
  if (!expected || typeof expected !== "object") return { answer: null, explanation: null };
  const key = expected as Record<string, unknown>;
  const correct = Array.isArray(key.correct) ? key.correct.map(text).filter((x): x is string => !!x).map(label).join(" or ") : text(key.correct);
  const points = Array.isArray(key.model_points) ? key.model_points.map(text).filter((x): x is string => !!x).join("; ") : null;
  return { answer: (correct && label(correct)) || points || null, explanation: text(key.explanation) };
}

export function itemResultText(r: PracticeItemResult, options: PracticeOption[] = []): string {
  const head = r.correct === true ? "Correct." : r.correct === false ? "Not quite." : "Answer recorded. This item isn't scored automatically.";
  const parts = [head];
  const { answer, explanation } = expectedText(r.expected, options);
  if (r.correct !== true && answer) parts.push(`${r.correct === null ? "Model answer" : "Expected"}: ${answer.replace(/\.$/, "")}.`);
  if (explanation) parts.push(explanation);
  if (r.feedback) parts.push(r.feedback);
  return parts.join(" ");
}
