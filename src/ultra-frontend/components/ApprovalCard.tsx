"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useAiPanel } from "@/lib/ai-panel-context";
import {
  commitPayload, commitPayloadProblems, gradeCommitRequirement, prefill, type GradeCommitRequirement,
} from "@/lib/grade-commit";

/** ApprovalRequestPayload in contracts/events.md. */
export interface PendingApproval {
  approval_id: string;
  step_id?: string;
  agent: string;
  action: string;
  preview: Record<string, unknown>;
  artifact_type: string;
}

const USER_CONTENT = /^<user_content[^>]*>([\s\S]*)<\/user_content>$/;

function label(key: string): string {
  return key.replace(/_/g, " ");
}

/** Preview strings arrive wrapped in prompt-injection delimiters (spec §14.5); show only the text. */
function text(v: string): string {
  return USER_CONTENT.exec(v)?.[1] ?? v;
}

/** Nested preview objects (the tool arguments, the drafted grade) as labelled fields. */
function PreviewValue({ value, depth }: { value: unknown; depth: number }) {
  if (value == null) return <>none</>;
  if (typeof value === "string") return <span className="whitespace-pre-wrap">{text(value)}</span>;
  if (typeof value !== "object") return <>{String(value)}</>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <>none</>;
    if (value.every((v) => v == null || typeof v !== "object")) return <>{value.map((v) => (typeof v === "string" ? text(v) : String(v))).join(", ")}</>;
    return (
      <ol className="list-decimal space-y-1 pl-4">
        {value.map((v, i) => <li key={i}><PreviewValue value={v} depth={depth + 1} /></li>)}
      </ol>
    );
  }
  return <PreviewFields entries={Object.entries(value)} depth={depth + 1} />;
}

function PreviewFields({ entries, depth }: { entries: [string, unknown][]; depth: number }) {
  return (
    <dl className={`space-y-1 ${depth > 0 ? "mt-1 border-l-2 border-amber-300 pl-2" : ""}`}>
      {entries.map(([k, v]) => {
        const nested = v != null && typeof v === "object" && !(Array.isArray(v) && v.every((x) => x == null || typeof x !== "object"));
        return (
          <div key={k} className={nested ? "" : "flex flex-wrap gap-1"}>
            <dt className="font-semibold">{label(k)}:</dt>
            <dd className="break-words"><PreviewValue value={v} depth={depth} /></dd>
          </div>
        );
      })}
    </dl>
  );
}

export type ApprovalDecision =
  | { decision: "approve" | "reject" }
  | { decision: "edit"; edited_payload: Record<string, unknown> };

const BUTTON = "min-h-6 rounded px-3 py-1 text-sm font-medium disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]";
const PRIMARY = `${BUTTON} bg-[#1a1a1a] text-white`;
const SECONDARY = `${BUTTON} border border-gray-500 bg-white text-gray-900`;
const INPUT = "mt-1 w-full rounded border border-gray-500 bg-white px-2 py-1 text-sm text-gray-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]";

/** A write-gated step paused for the person's decision; nothing is committed until Approve. */
export function ApprovalCard({ approval, busy, error, onDecide }: {
  approval: PendingApproval;
  busy: boolean;
  /** Why the last decision was not accepted; the card stays open for another try. */
  error?: string | null;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [approval.approval_id]);
  const entries = Object.entries(approval.preview ?? {});
  const commit = approval.artifact_type === "grade_commit" ? gradeCommitRequirement(approval.preview ?? {}) : null;

  return (
    <section aria-labelledby={`approval-${approval.approval_id}`} className="mr-4 rounded-lg border-2 border-amber-400 bg-amber-50 p-3 text-sm">
      <h3 id={`approval-${approval.approval_id}`} ref={headingRef} tabIndex={-1} className="flex items-center gap-1 font-semibold text-amber-950 outline-none">
        <ShieldCheck aria-hidden="true" className="h-4 w-4" />
        Approval needed: {approval.action}
      </h3>
      <p className="mt-1 text-xs text-amber-950">Requested by the {approval.agent.replace(/_/g, " ")} tool ({approval.artifact_type.replace(/_/g, " ")}).</p>
      {entries.length > 0 && (
        <div className="mt-2 text-xs text-gray-900">
          <PreviewFields entries={entries} depth={0} />
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
      {commit ? (
        <GradeCommitForm requirement={commit} busy={busy} onDecide={onDecide} />
      ) : (
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={busy} onClick={() => onDecide({ decision: "approve" })} className={PRIMARY}>
            Approve
          </button>
          <button type="button" disabled={busy} onClick={() => onDecide({ decision: "reject" })} className={SECONDARY}>
            Reject
          </button>
        </div>
      )}
    </section>
  );
}

/** A grade commits only with the instructor's own score on every criterion and a closing
 * comment; the generated draft scores are shown for reference, never sent. */
function GradeCommitForm({ requirement, busy, onDecide }: {
  requirement: GradeCommitRequirement;
  busy: boolean;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  const { stagedCommits } = useAiPanel();
  const [values, setValues] = useState(() => prefill(
    requirement, requirement.submissionId ? stagedCommits[requirement.submissionId] : undefined));
  const [problems, setProblems] = useState<string[]>([]);
  const commentId = useId();

  const submit = () => {
    const found = commitPayloadProblems(requirement, values);
    setProblems(found);
    if (found.length === 0) onDecide({ decision: "edit", edited_payload: commitPayload(requirement, values) });
  };

  return (
    <form className="mt-3 space-y-2 text-gray-900" onSubmit={(e) => { e.preventDefault(); submit(); }} noValidate>
      <fieldset>
        <legend className="text-xs font-semibold">Your final score for each criterion</legend>
        <ul className="mt-1 grid gap-2 sm:grid-cols-2">
          {requirement.keys.map((key) => (
            <li key={key}>
              <label className="text-sm">
                {label(key)}
                <span className="ml-1 text-xs text-gray-700">(generated draft: {String(requirement.draftScores[key] ?? "none")})</span>
                <input
                  type="number" min={0} step={1} required inputMode="numeric"
                  value={values.finalScores[key] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, finalScores: { ...v.finalScores, [key]: e.target.value } }))}
                  className={INPUT}
                />
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      <label htmlFor={commentId} className="block text-sm">Closing comment (required)</label>
      <textarea
        id={commentId} required rows={3} value={values.holisticMd}
        onChange={(e) => setValues((v) => ({ ...v, holisticMd: e.target.value }))}
        className={INPUT}
      />
      {problems.length > 0 && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          <p className="font-semibold">Can&apos;t commit yet:</p>
          <ul className="list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className={PRIMARY}>Commit with my scores</button>
        <button type="button" disabled={busy} onClick={() => onDecide({ decision: "reject" })} className={SECONDARY}>
          Reject
        </button>
      </div>
    </form>
  );
}
