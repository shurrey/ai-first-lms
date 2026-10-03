/**
 * The instructor's inputs for a `grade_commit` approval (events.md, POST /api/approval):
 * the decision must be `edit` with a final score for every key in
 * `preview.artifact.requires.final_scores` and a non-empty closing comment.
 */

export interface GradeCommitRequirement {
  gradeId: string;
  submissionId: string | null;
  keys: string[];
  draftScores: Record<string, unknown>;
}

export interface StagedCommit {
  /** Keyed by criterion key as the review page knows it. */
  finalScores: Record<string, string>;
  holisticMd: string;
}

function obj(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

export function normalizeKey(key: string): string {
  return key.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

export function gradeCommitRequirement(preview: Record<string, unknown>): GradeCommitRequirement | null {
  const artifact = obj(preview.artifact);
  const grade = obj(artifact?.grade);
  const requires = obj(artifact?.requires);
  const args = obj(preview.arguments);
  const gradeId = typeof grade?.grade_id === "string" ? grade.grade_id : typeof args?.grade_id === "string" ? args.grade_id : null;
  const keys = Array.isArray(requires?.final_scores) ? requires.final_scores.filter((k): k is string => typeof k === "string") : [];
  if (!gradeId || keys.length === 0) return null;
  return {
    gradeId,
    submissionId: typeof grade?.submission_id === "string" ? grade.submission_id : null,
    keys,
    draftScores: obj(grade?.scores) ?? {},
  };
}

/** Values staged on the review page for this submission, re-keyed to the required keys. */
export function prefill(req: GradeCommitRequirement, staged: StagedCommit | undefined): StagedCommit {
  const byNorm = new Map(Object.entries(staged?.finalScores ?? {}).map(([k, v]) => [normalizeKey(k), v]));
  return {
    finalScores: Object.fromEntries(req.keys.map((k) => [k, byNorm.get(normalizeKey(k)) ?? ""])),
    holisticMd: staged?.holisticMd ?? "",
  };
}

/** Problems that block the commit; empty when the payload is complete. */
export function commitPayloadProblems(req: GradeCommitRequirement, values: StagedCommit): string[] {
  const problems = req.keys
    .filter((k) => !/^\d+$/.test(values.finalScores[k]?.trim() ?? ""))
    .map((k) => `Enter a whole-number final score for ${k.replace(/_/g, " ")}.`);
  if (!values.holisticMd.trim()) problems.push("Write a closing comment.");
  return problems;
}

export function commitPayload(req: GradeCommitRequirement, values: StagedCommit): Record<string, unknown> {
  return {
    grade_id: req.gradeId,
    final_scores: Object.fromEntries(req.keys.map((k) => [k, Number(values.finalScores[k].trim())])),
    holistic_md: values.holisticMd.trim(),
  };
}
