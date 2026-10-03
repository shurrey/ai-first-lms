"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Minus, RotateCw } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useApiGet } from "@/lib/use-api";
import { AiGeneratedLabel } from "@/components/common/AiGeneratedLabel";
import {
  isAwaitingRelease,
  releaseFeedback,
  retryFeedback,
  type CriterionEdit,
  type CriterionFeedback,
  type FeedbackStatus,
  type SubmissionFeedback,
  type SubmissionHistory,
} from "@/lib/assessment";

const STATUS_TEXT: Record<FeedbackStatus, string> = {
  pending: "Feedback in progress",
  awaiting_release: "Awaiting instructor release",
  released: "Released",
  suppressed: "Suppressed",
  failed: "Generation failed",
  none: "No formative feedback",
};

// Feedback produced outside a turn is read by polling (contracts/events.md, Round 2 delivery).
const PENDING_POLL_MS = 5000;
const AWAITING_POLL_MS = 20000;

const buttonClass =
  "inline-flex min-h-6 items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Criterion-level formative feedback for one submission (spec §7.7). Faculty holding
 * `feedback_release` can edit, release or suppress feedback held under instructor_release.
 */
export function FeedbackCanvas({
  submissionId,
  onOpenPractice,
}: {
  submissionId: string;
  onOpenPractice?: (aiActionId: string) => void;
}) {
  const { me } = useAuth();
  const canRelease = me.capabilities.feedback_release !== undefined;
  const isStudent = me.active_role === "student";
  const path = `/api/feedback/${encodeURIComponent(submissionId)}`;
  const query = useQuery({
    queryKey: ["api", path],
    queryFn: () => apiJson<SubmissionFeedback>(path),
    retry: false,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "pending") return PENDING_POLL_MS;
      if (s === "awaiting_release" && isStudent) return AWAITING_POLL_MS;
      return false;
    },
  });
  const headingId = useId();
  const announce = useStatusAnnouncement(query.data?.status);

  let body: React.ReactNode;
  if (query.isPending) body = <p role="status">Loading feedback…</p>;
  else if (query.isError) {
    const err = query.error;
    body =
      err instanceof ApiError && err.status === 403 ? (
        <p role="alert">Your role can&apos;t view feedback on this submission.</p>
      ) : err instanceof ApiError && err.status === 404 ? (
        <p role="alert">This submission isn&apos;t available.</p>
      ) : (
        <p role="alert">Couldn&apos;t load feedback. Please try again.</p>
      );
  } else {
    // The API may leave out criteria the caller can't see; treat a missing list as empty.
    const fb = { ...query.data, criteria: query.data.criteria ?? [] };
    const unreleased = fb.status === "pending" || fb.status === "awaiting_release";
    const hidden = (isStudent || !canRelease) && unreleased;
    body = (
      <>
        {fb.student_name && !isStudent && <p className="text-xs text-muted-foreground">{fb.student_name}</p>}
        {fb.status === "failed" && (
          <FailedNotice path={path} submissionId={submissionId} />
        )}
        {fb.status === "failed" && (isStudent || fb.criteria.length === 0) ? null : hidden ? (
          <p className="text-xs">
            {!isStudent
              ? "This feedback hasn't been released to the student yet."
              : fb.status === "pending"
                ? "Feedback is being generated. This page checks for it automatically."
                : "Your instructor reviews this feedback before you see it. This page checks for it automatically."}
          </p>
        ) : fb.status === "suppressed" && isStudent ? (
          <p className="text-xs">Your instructor chose not to release generated feedback on this version.</p>
        ) : canRelease && isAwaitingRelease(fb) ? (
          <ReleaseForm feedback={fb} path={path} />
        ) : (
          <CriterionList criteria={fb.criteria} />
        )}
        {isStudent && fb.practice_set_ai_action_id && onOpenPractice && (
          <button
            type="button"
            onClick={() => onOpenPractice(fb.practice_set_ai_action_id as string)}
            className={`${buttonClass} border-primary bg-primary text-primary-foreground hover:bg-primary/90`}
          >
            Practice for this
          </button>
        )}
        <VersionHistory submissionId={submissionId} />
      </>
    );
  }

  return (
    <section aria-labelledby={headingId} className="space-y-3 text-sm" data-testid="feedback-canvas">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="text-base font-semibold">
          Feedback
        </h2>
        {query.data && (
          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs font-medium text-foreground">
            {STATUS_TEXT[query.data.status]}
            {query.data.release_mode === "instructor_release" ? " · instructor release" : " · released automatically"}
          </span>
        )}
      </div>
      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      {body}
    </section>
  );
}

/** A run that saved no feedback, or whose automatic release was refused; Retry starts another. */
function FailedNotice({ path, submissionId }: { path: string; submissionId: string }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retry = async () => {
    setBusy(true);
    setError(null);
    try {
      queryClient.setQueryData(["api", path], await retryFeedback(submissionId));
    } catch (err: unknown) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "Your role can't retry this feedback."
          : err instanceof ApiError && err.status === 409
            ? "This feedback is no longer marked as failed."
            : "Couldn't start another run. Please try again."
      );
      await queryClient.invalidateQueries({ queryKey: ["api", path] });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 rounded-md border border-destructive/60 bg-destructive/5 p-2">
      <p className="flex items-start gap-1 text-xs text-foreground">
        <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" />
        <span>
          <span className="font-semibold">Error:</span> feedback could not be generated or released for this
          version. The submission is saved.
        </span>
      </p>
      {error && <p role="alert" className="text-xs">{error}</p>}
      <button
        type="button"
        onClick={retry}
        disabled={busy}
        className={`${buttonClass} border-border bg-background text-foreground hover:bg-muted`}
      >
        <RotateCw aria-hidden="true" className="size-3.5" />
        {busy ? "Retrying…" : "Retry feedback"}
      </button>
    </div>
  );
}

/** Text for the live region when polling moves the feedback to a new status. */
function useStatusAnnouncement(status: FeedbackStatus | undefined): string {
  const prev = useRef<FeedbackStatus | undefined>(undefined);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (prev.current && status && prev.current !== status) {
      setMessage(`Feedback status: ${STATUS_TEXT[status]}.`);
    }
    prev.current = status;
  }, [status]);
  return message;
}

function scoreText(c: Pick<CriterionFeedback, "ai_score" | "final_score" | "level_label">): string {
  const score = c.final_score ?? c.ai_score;
  const parts = [score != null ? `Level ${score}` : null, c.level_label ?? null].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Level not shown";
}

function humanKey(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function CriterionList({ criteria }: { criteria: CriterionFeedback[] }) {
  if (criteria.length === 0) return <p className="text-xs text-muted-foreground">No criterion feedback yet.</p>;
  return (
    <ul className="space-y-3">
      {criteria.map((c) => (
        <li key={c.criterion_id} className="rounded-lg border border-border bg-card p-3">
          <CriterionBody c={c} />
        </li>
      ))}
    </ul>
  );
}

function CriterionBody({ c }: { c: CriterionFeedback }) {
  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{humanKey(c.criterion_key)}</h3>
        <span className="font-medium">{scoreText(c)}</span>
      </div>
      <p className="text-muted-foreground">{c.description}</p>
      {c.ai_rationale && <p>{c.ai_rationale}</p>}
      {c.evidence_spans.length > 0 && (
        <div>
          <p className="font-medium">Quoted from the submission</p>
          {c.evidence_spans.map((s, i) => (
            <blockquote key={i} className="mt-1 border-l-2 border-border pl-2 italic">
              &ldquo;{s.quote}&rdquo;
            </blockquote>
          ))}
        </div>
      )}
      {c.next_step && (
        <p>
          <span className="font-medium">Next step: </span>
          {c.next_step}
        </p>
      )}
      <AiGeneratedLabel aiActionIds={c.ai_action_id ? [c.ai_action_id] : []} />
    </div>
  );
}

interface Draft {
  score: string;
  rationale: string;
  next_step: string;
  suppress: boolean;
}

function initialDraft(c: CriterionFeedback): Draft {
  return {
    score: c.ai_score != null ? String(c.ai_score) : "",
    rationale: c.ai_rationale ?? "",
    next_step: c.next_step ?? "",
    suppress: false,
  };
}

/** Only fields the instructor changed are sent, so the server records an exact diff. */
function toEdit(c: CriterionFeedback, d: Draft): CriterionEdit | null {
  const edit: CriterionEdit = { criterion_id: c.criterion_id };
  let changed = false;
  const score = d.score === "" ? null : Number(d.score);
  if (score !== c.ai_score) {
    edit.score = score;
    changed = true;
  }
  if (d.rationale !== (c.ai_rationale ?? "")) {
    edit.rationale = d.rationale;
    changed = true;
  }
  if (d.next_step !== (c.next_step ?? "")) {
    edit.next_step = d.next_step;
    changed = true;
  }
  if (d.suppress) {
    edit.suppress = true;
    changed = true;
  }
  return changed ? edit : null;
}

function ReleaseForm({ feedback, path }: { feedback: SubmissionFeedback; path: string }) {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(feedback.criteria.map((c) => [c.criterion_id, initialDraft(c)]))
  );
  const [editing, setEditing] = useState<ReadonlySet<string>>(new Set());
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"release" | "suppress" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();

  const submit = async (action: "release" | "suppress") => {
    setBusy(action);
    setError(null);
    try {
      const edits =
        action === "release"
          ? feedback.criteria.map((c) => toEdit(c, drafts[c.criterion_id])).filter((e): e is CriterionEdit => e !== null)
          : undefined;
      const result = await releaseFeedback(feedback.submission_id, {
        action,
        ...(edits && edits.length > 0 && { edits }),
        reason: reason.trim() || null,
      });
      queryClient.setQueryData(["api", path], result);
      await queryClient.invalidateQueries({ queryKey: ["api", "/api/feedback/queue"], exact: false });
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "This feedback was already released or suppressed, or the course releases feedback automatically."
          : err instanceof ApiError && err.status === 403
            ? "Your role can't release feedback for this course."
            : "Couldn't save your decision. Please try again."
      );
    } finally {
      setBusy(null);
    }
  };

  const update = (id: string, patch: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  return (
    <div className="space-y-3">
      <p className="text-xs">
        The student sees none of this until you release it. Edit any criterion first; your changes
        are recorded alongside the generated text.
      </p>
      <ul className="space-y-3">
        {feedback.criteria.map((c) => {
          const d = drafts[c.criterion_id];
          const isEditing = editing.has(c.criterion_id);
          return (
            <li key={c.criterion_id} className="rounded-lg border border-border bg-card p-3">
              <CriterionBody c={c} />
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
                <button
                  type="button"
                  aria-expanded={isEditing}
                  onClick={() =>
                    setEditing((prev) => {
                      const next = new Set(prev);
                      if (next.has(c.criterion_id)) next.delete(c.criterion_id);
                      else next.add(c.criterion_id);
                      return next;
                    })
                  }
                  className={`${buttonClass} border-border bg-background hover:bg-muted`}
                >
                  {isEditing ? "Done editing" : "Edit"}
                  <span className="sr-only"> {humanKey(c.criterion_key)}</span>
                </button>
                <label className="inline-flex min-h-6 items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={d.suppress}
                    onChange={(e) => update(c.criterion_id, { suppress: e.target.checked })}
                    className="h-4 w-4"
                  />
                  Don&apos;t release {humanKey(c.criterion_key)}
                </label>
              </div>
              {isEditing && (
                <CriterionEditor
                  criterion={c}
                  draft={d}
                  onChange={(patch) => update(c.criterion_id, patch)}
                />
              )}
            </li>
          );
        })}
      </ul>
      <div className="space-y-1 text-xs">
        <label htmlFor={reasonId} className="font-medium">
          Note for the record (optional)
        </label>
        <textarea
          id={reasonId}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-input bg-background p-2"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => submit("release")}
          disabled={busy !== null}
          className={`${buttonClass} border-primary bg-primary text-primary-foreground hover:bg-primary/90`}
        >
          {busy === "release" ? "Releasing…" : "Release to student"}
        </button>
        <button
          type="button"
          onClick={() => submit("suppress")}
          disabled={busy !== null}
          className={`${buttonClass} border-border bg-background hover:bg-muted`}
        >
          {busy === "suppress" ? "Suppressing…" : "Suppress all"}
        </button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function CriterionEditor({
  criterion,
  draft,
  onChange,
}: {
  criterion: CriterionFeedback;
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const base = useId();
  const name = humanKey(criterion.criterion_key);
  const field = "w-full rounded-md border border-input bg-background p-2";
  return (
    <fieldset className="mt-2 space-y-2 text-xs">
      <legend className="sr-only">Edit {name}</legend>
      <div>
        <label htmlFor={`${base}-score`} className="font-medium">
          {name} level
        </label>
        <input
          id={`${base}-score`}
          type="number"
          min={0}
          inputMode="numeric"
          value={draft.score}
          onChange={(e) => onChange({ score: e.target.value })}
          className={`${field} max-w-24`}
        />
      </div>
      <div>
        <label htmlFor={`${base}-rationale`} className="font-medium">
          {name} feedback
        </label>
        <textarea
          id={`${base}-rationale`}
          rows={3}
          value={draft.rationale}
          onChange={(e) => onChange({ rationale: e.target.value })}
          className={field}
        />
      </div>
      <div>
        <label htmlFor={`${base}-next`} className="font-medium">
          {name} next step
        </label>
        <textarea
          id={`${base}-next`}
          rows={2}
          value={draft.next_step}
          onChange={(e) => onChange({ next_step: e.target.value })}
          className={field}
        />
      </div>
    </fieldset>
  );
}

function DeltaIndicator({ delta }: { delta: number | null }) {
  if (delta == null) return <span className="text-muted-foreground">first version</span>;
  if (delta > 0)
    return (
      <span className="inline-flex items-center gap-0.5">
        <ArrowUp aria-hidden="true" className="h-3 w-3" />
        up {delta}
      </span>
    );
  if (delta < 0)
    return (
      <span className="inline-flex items-center gap-0.5">
        <ArrowDown aria-hidden="true" className="h-3 w-3" />
        down {Math.abs(delta)}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-0.5">
      <Minus aria-hidden="true" className="h-3 w-3" />
      no change
    </span>
  );
}

/** Version chain with per-criterion change, shown as text plus an icon (not colour alone). */
function VersionHistory({ submissionId }: { submissionId: string }) {
  const { data } = useApiGet<SubmissionHistory>(`/api/submissions/${encodeURIComponent(submissionId)}/history`);
  if (!data || data.versions.length < 2) return null;
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Version history table">
      <table className="w-full border-collapse text-xs">
        <caption className="mb-1 text-left text-sm font-semibold">Version history</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="px-2 py-1 text-left font-medium">Version</th>
            <th scope="col" className="px-2 py-1 text-left font-medium">Criterion changes</th>
          </tr>
        </thead>
        <tbody>
          {data.versions.map(({ submission, criteria }) => (
            <tr key={submission.id} className="border-b border-border/50 align-top">
              <th scope="row" className="px-2 py-1 text-left font-normal">
                {submission.version} ({submission.status}) · {new Date(submission.submitted_at).toLocaleDateString()}
              </th>
              <td className="px-2 py-1">
                <ul className="space-y-0.5">
                  {criteria.map((c) => (
                    <li key={c.criterion_id}>
                      {humanKey(c.criterion_key)}: {c.score ?? "–"} <DeltaIndicator delta={c.delta} />
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
