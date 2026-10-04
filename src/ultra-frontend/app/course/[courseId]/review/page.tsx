"use client";

import { use, useCallback, useEffect, useId, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Award, ClipboardCheck, MessageSquareText } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAiPanel } from "@/lib/ai-panel-context";
import { formatDateTime, humanizeKey, showsReviewQueueTab } from "@/lib/assessment";
import {
  commitProblems, commitPrompt, initialEdit, isCommitted, releaseEdits, type CriterionEdit, type FinalToGrade,
} from "@/lib/review";
import { retryFeedback } from "@/lib/use-feedback";
import { NoAccess } from "@/components/NoAccess";
import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";
import type { CriterionFeedback, Page, PendingCredential, Submission, SubmissionFeedback } from "@/lib/types";

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

function errorText(err: unknown): string | null {
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return null;
  return err instanceof Error ? err.message : String(err);
}

/** Returns [state, reload (shows loading), update, refresh (keeps the current list on screen until new data lands)]. */
function useLoad<T>(fetcher: (() => Promise<T>) | null): [Load<T>, () => void, (fn: (d: T) => T) => void, () => void] {
  const [state, setState] = useState<Load<T>>({ status: "loading" });
  const load = useCallback(() => {
    if (!fetcher) return;
    setState({ status: "loading" });
    fetcher()
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        const message = errorText(err);
        if (message) setState({ status: "error", message });
      });
  }, [fetcher]);
  useEffect(load, [load]);
  const update = useCallback((fn: (d: T) => T) => {
    setState((s) => (s.status === "ready" ? { status: "ready", data: fn(s.data) } : s));
  }, []);
  const refresh = useCallback(() => {
    if (!fetcher) return;
    fetcher()
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        const message = errorText(err);
        if (message) setState({ status: "error", message });
      });
  }, [fetcher]);
  return [state, load, update, refresh];
}

const BUTTON_PRIMARY = "min-h-6 rounded bg-[#1a1a1a] px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]";
const BUTTON_SECONDARY = "min-h-6 rounded border border-gray-500 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 hover:bg-gray-50 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]";
const INPUT = "mt-1 w-full rounded border border-gray-400 p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]";

export default function ReviewQueuePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { capabilities } = useAuth();
  const [announcement, setAnnouncement] = useState("");
  if (!showsReviewQueueTab(capabilities)) return <NoAccess />;

  return (
    <div className="max-w-5xl space-y-6 p-6">
      <div role="status" aria-live="polite" className="sr-only">{announcement}</div>
      <div>
        <h2 className="text-lg font-semibold">Review Queue</h2>
        <p className="text-sm text-gray-700">
          Generated feedback waits here until you release, edit or suppress it. Grades are committed only with your scores and closing comment.
        </p>
      </div>
      {capabilities.feedback_release && <FeedbackQueue courseId={courseId} announce={setAnnouncement} />}
      {capabilities.grade_commit && <GradesToCommit courseId={courseId} />}
      {capabilities.badge_approve && <CredentialsToApprove courseId={courseId} announce={setAnnouncement} />}
    </div>
  );
}

function SectionShell({ id, icon: Icon, title, count, children }: {
  id: string; icon: React.ElementType; title: string; count: number | null; children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 id={id} className="flex items-center gap-2 text-base font-semibold">
        <Icon aria-hidden="true" className="h-4 w-4" />
        {title}{count != null ? ` (${count})` : ""}
      </h3>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

function LoadBlock<T>({ state, retry, label, children }: { state: Load<T>; retry: () => void; label: string; children: (d: T) => React.ReactNode }) {
  if (state.status === "loading") return <p className="text-sm text-gray-700">Loading {label}…</p>;
  if (state.status === "error") {
    return (
      <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
        Couldn&apos;t load {label}: {state.message}
        <button type="button" onClick={retry} className={`ml-2 ${BUTTON_SECONDARY}`}>Try again</button>
      </div>
    );
  }
  return <>{children(state.data)}</>;
}

function SubmissionText({ submissionId }: { submissionId: string }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<Load<Submission> | null>(null);
  const panelId = useId();
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !state) {
      setState({ status: "loading" });
      apiJson<Submission>(`/api/submissions/${encodeURIComponent(submissionId)}`, { reportForbidden: false })
        .then((data) => setState({ status: "ready", data }))
        .catch((err: unknown) => setState({ status: "error", message: errorText(err) ?? "Your role can't open this submission." }));
    }
  };
  return (
    <div>
      <button type="button" onClick={toggle} aria-expanded={open} aria-controls={panelId} className="min-h-6 text-sm text-[#1a5fb4] underline">
        {open ? "Hide submission text" : "Show submission text"}
      </button>
      {open && (
        <div id={panelId} className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-2 text-sm text-gray-900">
          {state?.status === "ready" ? state.data.body_md ?? "No text submitted." : state?.status === "error" ? state.message : "Loading…"}
        </div>
      )}
    </div>
  );
}

// ---- feedback awaiting release ----

function FeedbackQueue({ courseId, announce }: { courseId: string; announce: (s: string) => void }) {
  const fetcher = useCallback(
    () => apiJson<Page<SubmissionFeedback>>(`/api/feedback/queue?course_id=${encodeURIComponent(courseId)}`).then((p) => p.items),
    [courseId],
  );
  const [state, retry, update] = useLoad(fetcher);
  const count = state.status === "ready" ? state.data.length : null;
  return (
    <SectionShell id="queue-feedback" icon={MessageSquareText} title="Feedback awaiting release" count={count}>
      <LoadBlock state={state} retry={retry} label="feedback awaiting release">
        {(items) => items.length === 0 ? <p className="text-sm text-gray-700">No feedback is waiting for release.</p> : (
          <ul className="space-y-3">
            {items.map((f) => (
              <li key={f.submission_id}>
                <FeedbackReleaseCard
                  feedback={f}
                  courseId={courseId}
                  onDone={(msg) => {
                    update((list) => list.filter((x) => x.submission_id !== f.submission_id));
                    announce(msg);
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </LoadBlock>
    </SectionShell>
  );
}

function AlignmentLink({ courseId, assignmentId, title }: { courseId: string; assignmentId: string; title: string | null }) {
  return (
    <Link href={`/course/${courseId}/alignment/${assignmentId}`} className="inline-flex min-h-6 items-center text-xs text-[#1a5fb4] underline">
      Outcome alignment for {title ?? "this assignment"}
    </Link>
  );
}

function FeedbackReleaseCard({ feedback, courseId, onDone }: { feedback: SubmissionFeedback; courseId: string; onDone: (msg: string) => void }) {
  const { activeRole, findEnrollment } = useAuth();
  const teaches = activeRole === "faculty" && findEnrollment(courseId)?.role === "faculty";
  const [edits, setEdits] = useState<Record<string, CriterionEdit>>(
    () => Object.fromEntries(feedback.criteria.map((c) => [c.criterion_id, initialEdit(c)])),
  );
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();
  const who = feedback.student_name ?? "A student";

  const send = async (action: "release" | "suppress") => {
    setBusy(true);
    setError(null);
    const body = action === "release"
      ? { action, edits: releaseEdits(feedback.criteria, edits), reason: reason.trim() || null }
      : { action, reason: reason.trim() || null };
    try {
      await apiJson<SubmissionFeedback>(`/api/feedback/${encodeURIComponent(feedback.submission_id)}/release`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        reportForbidden: false,
      });
      onDone(action === "release" ? `Feedback for ${who} released.` : `Feedback for ${who} suppressed.`);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 403) setError("Your role can't release feedback in this course.");
      else setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const set = (id: string, patch: Partial<CriterionEdit>) => setEdits((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  return (
    <article aria-label={`Feedback for ${who}`} className="rounded-lg border border-gray-300 p-3">
      <h4 className="text-sm font-semibold">{who}</h4>
      {teaches && feedback.assignment_id && <AlignmentLink courseId={courseId} assignmentId={feedback.assignment_id} title={`${who}'s assignment`} />}
      <SubmissionText submissionId={feedback.submission_id} />
      {feedback.status === "failed" && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-red-300 bg-red-50 p-2">
          <p className="flex items-center gap-1 text-sm text-red-900">
            <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
            <span><span className="font-semibold">Error:</span> the automatic release of this feedback failed.</span>
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              const problem = await retryFeedback(feedback.submission_id);
              setBusy(false);
              if (problem) setError(problem);
              else onDone(`Feedback for ${who} is being retried.`);
            }}
            className={BUTTON_SECONDARY}
          >
            Retry release
          </button>
        </div>
      )}
      <ul className="mt-2 space-y-2">
        {feedback.criteria.map((c) => {
          const e = edits[c.criterion_id];
          const isEditing = !!editing[c.criterion_id];
          const name = humanizeKey(c.criterion_key);
          return (
            <li key={c.criterion_id} className="rounded border border-gray-200 p-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-semibold">{name}</span>
                <span className="text-sm text-gray-900">
                  Generated level: {c.ai_score ?? "none"}{c.level_label ? ` · ${c.level_label}` : ""}
                </span>
              </div>
              {!isEditing ? (
                <>
                  {c.ai_rationale && <p className="mt-1 text-sm text-gray-800">{c.ai_rationale}</p>}
                  {c.evidence_spans.map((s, i) => (
                    <blockquote key={i} className="mt-1 border-l-4 border-gray-400 bg-gray-50 px-2 text-sm italic">&ldquo;{s.quote}&rdquo;</blockquote>
                  ))}
                  {c.next_step && <p className="mt-1 text-sm"><span className="font-semibold">Next step:</span> {c.next_step}</p>}
                </>
              ) : (
                <div className="mt-2 grid gap-2 sm:grid-cols-[8rem_1fr]">
                  <label className="text-xs font-medium text-gray-800">
                    Level for {name}
                    <input type="number" min={0} step={1} value={e.score} onChange={(ev) => set(c.criterion_id, { score: ev.target.value })} className={INPUT} />
                  </label>
                  <label className="text-xs font-medium text-gray-800">
                    Rationale for {name}
                    <textarea rows={2} value={e.rationale} onChange={(ev) => set(c.criterion_id, { rationale: ev.target.value })} className={INPUT} />
                  </label>
                  <label className="text-xs font-medium text-gray-800 sm:col-span-2">
                    Next step for {name}
                    <textarea rows={2} value={e.next_step} onChange={(ev) => set(c.criterion_id, { next_step: ev.target.value })} className={INPUT} />
                  </label>
                </div>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <button type="button" aria-expanded={isEditing} onClick={() => setEditing((p) => ({ ...p, [c.criterion_id]: !isEditing }))} className={BUTTON_SECONDARY}>
                  {isEditing ? `Done editing ${name}` : `Edit ${name}`}
                </button>
                <label className="flex min-h-6 items-center gap-2 text-sm text-gray-900">
                  <input type="checkbox" checked={e.suppress} onChange={(ev) => set(c.criterion_id, { suppress: ev.target.checked })} className="h-4 w-4" />
                  Suppress {name}
                </label>
              </div>
              <AiGeneratedLabel aiActionId={c.ai_action_id} />
            </li>
          );
        })}
      </ul>
      <label htmlFor={reasonId} className="mt-3 block text-xs font-medium text-gray-800">Reason (optional, recorded with your decision)</label>
      <input id={reasonId} value={reason} onChange={(e) => setReason(e.target.value)} className={INPUT} />
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => send("release")} className={BUTTON_PRIMARY}>Release to {who}</button>
        <button type="button" disabled={busy} onClick={() => send("suppress")} className={BUTTON_SECONDARY}>Suppress all feedback</button>
      </div>
    </article>
  );
}

// ---- grades to commit ----

const MAX_SUBMISSION_PAGES = 20;

async function loadFinals(courseId: string): Promise<FinalToGrade[]> {
  const submissions: Submission[] = [];
  let cursor: string | null | undefined = null;
  for (let i = 0; i < MAX_SUBMISSION_PAGES; i++) {
    const query = new URLSearchParams({ course_id: courseId });
    if (cursor) query.set("cursor", cursor);
    const page: Page<Submission> = await apiJson<Page<Submission>>(`/api/submissions?${query}`);
    submissions.push(...page.items);
    cursor = page.next_cursor;
    if (!cursor) break;
  }
  const finals = submissions.filter((s) => s.status === "final");
  const withFeedback = await Promise.all(finals.map(async (submission) => ({
    submission,
    feedback: await apiJson<SubmissionFeedback>(`/api/feedback/${encodeURIComponent(submission.id)}`),
  })));
  return withFeedback.filter((f) => !isCommitted(f.feedback));
}

function GradesToCommit({ courseId }: { courseId: string }) {
  const fetcher = useCallback(() => loadFinals(courseId), [courseId]);
  const [state, retry, , refresh] = useLoad(fetcher);
  const { turnsCompleted } = useAiPanel();
  // A commit is approved inside an AI panel turn; re-read the list once any turn ends.
  useEffect(() => {
    if (turnsCompleted > 0) refresh();
  }, [turnsCompleted, refresh]);
  const count = state.status === "ready" ? state.data.length : null;
  return (
    <SectionShell id="queue-grades" icon={ClipboardCheck} title="Grades to commit" count={count}>
      <LoadBlock state={state} retry={retry} label="grades to commit">
        {(items) => items.length === 0 ? <p className="text-sm text-gray-700">No final submissions are waiting for a grade.</p> : (
          <ul className="space-y-3">
            {items.map((f) => <li key={f.submission.id}><GradeCommitCard item={f} courseId={courseId} /></li>)}
          </ul>
        )}
      </LoadBlock>
    </SectionShell>
  );
}

function GradeCommitCard({ item, courseId }: { item: FinalToGrade; courseId: string }) {
  const { open, stageCommit } = useAiPanel();
  const { activeRole, findEnrollment } = useAuth();
  const teaches = activeRole === "faculty" && findEnrollment(courseId)?.role === "faculty";
  const [scores, setScores] = useState<Record<string, string>>({});
  const [closing, setClosing] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [handedOff, setHandedOff] = useState(false);
  const closingId = useId();
  const who = item.feedback.student_name ?? "Student";
  const criteria = item.feedback.criteria;

  const commit = () => {
    const found = commitProblems(criteria, scores, closing);
    setProblems(found);
    if (found.length > 0) return;
    setHandedOff(true);
    stageCommit(item.submission.id, {
      finalScores: Object.fromEntries(criteria.map((c) => [c.criterion_key, scores[c.criterion_id].trim()])),
      holisticMd: closing.trim(),
    });
    open(commitPrompt(item, scores, closing));
  };

  return (
    <article aria-label={`Grade for ${who}`} className="rounded-lg border border-gray-300 p-3">
      <h4 className="text-sm font-semibold">{who}</h4>
      <p className="text-xs text-gray-700">{item.submission.assignment_title ?? "Assignment"} · final version {item.submission.version} · submitted {formatDateTime(item.submission.submitted_at)}</p>
      {teaches && <AlignmentLink courseId={courseId} assignmentId={item.submission.assignment_id} title={item.submission.assignment_title ?? null} />}
      <SubmissionText submissionId={item.submission.id} />
      <form className="mt-2 space-y-2" onSubmit={(e) => { e.preventDefault(); commit(); }} noValidate>
        <fieldset>
          <legend className="text-xs font-semibold text-gray-800">Your final score for each criterion</legend>
          <ul className="mt-1 grid gap-2 sm:grid-cols-2">
            {criteria.map((c) => (
              <li key={c.criterion_id}>
                <label className="text-sm text-gray-900">
                  {humanizeKey(c.criterion_key)}
                  <span className="ml-1 text-xs text-gray-700">(draft score: {c.ai_score ?? "none"})</span>
                  <input
                    type="number" min={0} step={1} required
                    value={scores[c.criterion_id] ?? ""}
                    onChange={(e) => setScores((p) => ({ ...p, [c.criterion_id]: e.target.value }))}
                    className={INPUT}
                  />
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
        <label htmlFor={closingId} className="block text-sm text-gray-900">Closing comment (required)</label>
        <textarea id={closingId} required rows={3} value={closing} onChange={(e) => setClosing(e.target.value)} className={INPUT} />
        {problems.length > 0 && (
          <div role="alert" className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800">
            <p className="font-semibold">Can&apos;t commit yet:</p>
            <ul className="list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" className={BUTTON_PRIMARY}>Commit grade</button>
          {handedOff && (
            <span className="text-sm text-gray-800">Confirm your scores and comment in the AI assistant panel. Nothing is committed until you approve.</span>
          )}
        </div>
      </form>
    </article>
  );
}

// ---- credentials to approve ----

function CredentialsToApprove({ courseId, announce }: { courseId: string; announce: (s: string) => void }) {
  const fetcher = useCallback(
    () => apiJson<{ pending?: PendingCredential[]; error?: string }>(`/api/pending-credentials/${encodeURIComponent(courseId)}`)
      .then((d) => {
        if (d.error) throw new Error(d.error);
        return d.pending ?? [];
      }),
    [courseId],
  );
  const [state, retry, update] = useLoad(fetcher);
  const count = state.status === "ready" ? state.data.length : null;
  return (
    <SectionShell id="queue-credentials" icon={Award} title="Credentials to approve" count={count}>
      <LoadBlock state={state} retry={retry} label="pending credentials">
        {(items) => items.length === 0 ? <p className="text-sm text-gray-700">No credentials are waiting for review.</p> : (
          <ul className="space-y-2">
            {items.map((c) => (
              <li key={c.id}>
                <CredentialRow
                  credential={c}
                  onDone={(msg) => {
                    update((list) => list.filter((x) => x.id !== c.id));
                    announce(msg);
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </LoadBlock>
    </SectionShell>
  );
}

function CredentialRow({ credential, onDone }: { credential: PendingCredential; onDone: (msg: string) => void }) {
  const { personId } = useAuth();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();
  const label = `${credential.credential_title} for ${credential.student_name}`;

  const decide = async (kind: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    const id = encodeURIComponent(credential.id);
    const url = kind === "approve" ? `/api/approve-credential/${id}` : `/api/reject-credential/${id}`;
    const body = kind === "approve" ? { reviewer_id: personId } : { reviewer_id: personId, reason: reason.trim() || null };
    try {
      const result = await apiJson<{ error?: string }>(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        reportForbidden: false,
      });
      if (result && typeof result === "object" && result.error) throw new Error(result.error);
      onDone(kind === "approve" ? `${label} approved.` : `${label} rejected.`);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 403) setError("Your role can't decide on this credential.");
      else setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-300 p-3">
      <p className="text-sm font-medium text-gray-900">{credential.credential_title}</p>
      <p className="text-xs text-gray-700">{credential.student_name} · recommended {formatDateTime(credential.created_at)}</p>
      {error && <p role="alert" className="mt-1 text-sm text-red-800">{error}</p>}
      {!rejecting ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => decide("approve")} aria-label={`Approve ${label}`} className={BUTTON_PRIMARY}>Approve</button>
          <button type="button" disabled={busy} onClick={() => setRejecting(true)} aria-label={`Reject ${label}`} className={BUTTON_SECONDARY}>Reject</button>
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          <label htmlFor={reasonId} className="block text-xs font-medium text-gray-800">Reason for rejecting (optional)</label>
          <input id={reasonId} autoFocus value={reason} onChange={(e) => setReason(e.target.value)} className={INPUT} />
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => decide("reject")} className={BUTTON_PRIMARY}>Confirm reject</button>
            <button type="button" onClick={() => setRejecting(false)} className={BUTTON_SECONDARY}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
