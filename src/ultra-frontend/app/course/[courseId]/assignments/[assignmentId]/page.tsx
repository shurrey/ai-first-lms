"use client";

import { use, useCallback, useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { AlertTriangle, Dumbbell, RotateCw, Send } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { FEEDBACK_STATUS_TEXT, feedbackStillOpen, formatDateTime, humanizeKey, showsAssignmentsTab } from "@/lib/assessment";
import { retryFeedback, useFeedbackPoll } from "@/lib/use-feedback";
import { NoAccess } from "@/components/NoAccess";
import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";
import { ChangeIndicator } from "@/components/assessment/ChangeIndicator";
import { CriterionFeedbackList } from "@/components/assessment/CriterionFeedbackList";
import type { FeedbackStatus, Page, Submission, SubmissionHistory, SubmissionStatus } from "@/lib/types";

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

function quietError(err: unknown): string | null {
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return null;
  return err instanceof Error ? err.message : String(err);
}

export default function AssignmentPage({ params }: { params: Promise<{ courseId: string; assignmentId: string }> }) {
  const { courseId, assignmentId } = use(params);
  const { activeRole, capabilities } = useAuth();
  if (!showsAssignmentsTab(activeRole, capabilities)) return <NoAccess />;
  return <Assignment courseId={courseId} assignmentId={assignmentId} />;
}

function Assignment({ courseId, assignmentId }: { courseId: string; assignmentId: string }) {
  const [versions, setVersions] = useState<Load<Submission[]>>({ status: "loading" });
  const [history, setHistory] = useState<SubmissionHistory | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const loadHistory = useCallback((latestId: string) => {
    apiJson<SubmissionHistory>(`/api/submissions/${encodeURIComponent(latestId)}/history`)
      .then(setHistory)
      .catch((err: unknown) => {
        const message = quietError(err);
        if (message) setAnnouncement(`Couldn't load version history: ${message}`);
      });
  }, []);

  const loadVersions = useCallback(() => {
    apiJson<Page<Submission>>(`/api/submissions?assignment_id=${encodeURIComponent(assignmentId)}&all_versions=true`)
      .then((page) => {
        const sorted = [...page.items].sort((a, b) => a.version - b.version);
        setVersions({ status: "ready", data: sorted });
        const latest = sorted.at(-1);
        setSelectedId((current) => current ?? latest?.id ?? null);
        if (latest) loadHistory(latest.id);
      })
      .catch((err: unknown) => {
        const message = quietError(err);
        if (message) setVersions({ status: "error", message });
      });
  }, [assignmentId, loadHistory]);
  useEffect(loadVersions, [loadVersions]);

  const onSubmitted = (submission: Submission) => {
    setSelectedId(submission.id);
    setAnnouncement(`Version ${submission.version} submitted as ${submission.status}.`);
    loadVersions();
  };

  if (versions.status === "loading") return <p role="status" className="p-6 text-sm text-gray-700">Loading assignment…</p>;
  if (versions.status === "error") {
    return (
      <div role="alert" className="m-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        Couldn&apos;t load this assignment: {versions.message}
      </div>
    );
  }

  const all = versions.data;
  const latest = all.at(-1) ?? null;
  const selected = all.find((s) => s.id === selectedId) ?? latest;
  const title = latest?.assignment_title ?? "Assignment";

  return (
    <div className="grid max-w-6xl gap-6 p-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div aria-live="polite" role="status" className="sr-only">{announcement}</div>
      <div className="space-y-4 lg:col-span-2">
        <Link href={`/course/${courseId}/assignments`} className="text-sm text-[#1a5fb4] underline">Back to your assignments</Link>
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      <div className="space-y-6">
        <SubmitForm assignmentId={assignmentId} latest={latest} onSubmitted={onSubmitted} />
        <VersionHistory versions={all} history={history} selectedId={selected?.id ?? null} onSelect={setSelectedId} />
      </div>
      {selected && (
        <FeedbackPanel
          courseId={courseId}
          submission={selected}
          onReleased={() => {
            setAnnouncement(`Feedback for version ${selected.version} is ready.`);
            if (latest) loadHistory(latest.id);
          }}
        />
      )}
    </div>
  );
}

function SubmitForm({ assignmentId, latest, onSubmitted }: {
  assignmentId: string;
  latest: Submission | null;
  onSubmitted: (s: Submission) => void;
}) {
  const [body, setBody] = useState(latest?.body_md ?? "");
  const [busy, setBusy] = useState<SubmissionStatus | null>(null);
  const [confirmFinal, setConfirmFinal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bodyId = useId();
  const hintId = useId();
  const loadedFor = useRef<string | null>(latest?.id ?? null);

  useEffect(() => {
    if (latest && loadedFor.current !== latest.id) {
      loadedFor.current = latest.id;
      setBody(latest.body_md ?? "");
    }
  }, [latest]);

  if (latest?.status === "final") {
    return (
      <section aria-labelledby="submit-heading" className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 id="submit-heading" className="text-sm font-semibold">Submission</h3>
        <p className="mt-1 text-sm text-gray-700">You submitted your final version on {formatDateTime(latest.submitted_at)}. Your instructor grades it.</p>
      </section>
    );
  }

  const submit = async (status: SubmissionStatus) => {
    if (!body.trim()) {
      setError("Write your work before submitting.");
      return;
    }
    setBusy(status);
    setError(null);
    try {
      const created = await apiJson<Submission>("/api/submissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assignment_id: assignmentId, status, body_md: body, attachments: [], parent_id: latest?.id ?? null }),
        reportForbidden: false,
      });
      setConfirmFinal(false);
      onSubmitted(created);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) return;
      if (err instanceof ApiError && err.status === 403) setError("Your role can't submit work in this course.");
      else if (err instanceof ApiError && err.status === 409) setError(`Not submitted: ${err.message}`);
      else setError(`Not submitted: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="submit-heading" className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 id="submit-heading" className="text-sm font-semibold">{latest ? `Revise version ${latest.version}` : "Your submission"}</h3>
      <p id={hintId} className="mt-1 text-xs text-gray-700">
        A draft gets criterion feedback and can be revised. A final version goes to your instructor for grading and can&apos;t be revised.
      </p>
      <label htmlFor={bodyId} className="mt-3 block text-sm font-medium text-gray-900">Your work</label>
      <textarea
        id={bodyId}
        aria-describedby={hintId}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={12}
        className="mt-1 w-full rounded border border-gray-400 p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
      />
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => submit("draft")}
          disabled={busy !== null}
          className="inline-flex min-h-6 items-center gap-1 rounded bg-[#1a1a1a] px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
        >
          <Send aria-hidden="true" className="h-4 w-4" />
          {busy === "draft" ? "Submitting draft…" : "Submit draft"}
        </button>
        {!confirmFinal ? (
          <button
            type="button"
            onClick={() => setConfirmFinal(true)}
            disabled={busy !== null}
            className="min-h-6 rounded border border-gray-500 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 hover:bg-gray-50 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
          >
            Submit final
          </button>
        ) : (
          <div role="group" aria-label="Confirm final submission" className="flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1">
            <span className="text-sm text-amber-950">Submit as final? You can&apos;t revise after this.</span>
            <button
              type="button"
              autoFocus
              onClick={() => submit("final")}
              disabled={busy !== null}
              className="min-h-6 rounded bg-[#1a1a1a] px-3 py-1 text-sm font-medium text-white disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
            >
              {busy === "final" ? "Submitting final…" : "Yes, submit final"}
            </button>
            <button
              type="button"
              onClick={() => setConfirmFinal(false)}
              className="min-h-6 rounded border border-gray-500 bg-white px-3 py-1 text-sm font-medium text-gray-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function VersionHistory({ versions, history, selectedId, onSelect }: {
  versions: Submission[];
  history: SubmissionHistory | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (versions.length === 0) return null;
  const criteriaFor = (id: string) => history?.versions.find((v) => v.submission.id === id)?.criteria ?? [];
  return (
    <section aria-labelledby="history-heading" className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 id="history-heading" className="text-sm font-semibold">Version history</h3>
      <ol className="mt-2 space-y-2">
        {[...versions].reverse().map((v) => {
          const criteria = criteriaFor(v.id);
          const isSelected = v.id === selectedId;
          return (
            <li key={v.id} className={clsx("rounded-lg border p-3", isSelected ? "border-[#1a1a1a] bg-gray-50" : "border-gray-200")}>
              <button
                type="button"
                onClick={() => onSelect(v.id)}
                aria-pressed={isSelected}
                className="min-h-6 text-left text-sm font-medium text-[#1a5fb4] underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
              >
                Version {v.version} ({v.status}) · {formatDateTime(v.submitted_at)}
              </button>
              {isSelected && <span className="ml-2 text-xs font-semibold text-gray-800">Showing feedback</span>}
              {criteria.length > 0 && (
                <ul aria-label={`Criterion changes in version ${v.version}`} className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  {criteria.map((c) => (
                    <li key={c.criterion_id} className="flex items-center gap-1 text-xs text-gray-900">
                      <span>{humanizeKey(c.criterion_key)}: {c.score ?? "not shown"}</span>
                      <ChangeIndicator delta={c.delta} isFirst={v.version === 1} />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function FeedbackPanel({ courseId, submission, onReleased }: { courseId: string; submission: Submission; onReleased: () => void }) {
  const [restart, setRestart] = useState(0);
  const state = useFeedbackPoll(submission.id, restart);
  const lastStatus = useRef<{ id: string; status: FeedbackStatus } | null>(null);
  const status = state.status === "ready" ? state.feedback.status : null;

  useEffect(() => {
    if (!status) return;
    const prev = lastStatus.current;
    lastStatus.current = { id: submission.id, status };
    if (prev?.id === submission.id && feedbackStillOpen(prev.status) && status === "released") onReleased();
  }, [status, submission.id, onReleased]);

  return (
    <section aria-labelledby="feedback-heading" className="space-y-3 rounded-xl border border-gray-200 bg-white p-4">
      <h3 id="feedback-heading" className="text-sm font-semibold">Feedback on version {submission.version}</h3>
      {(state.status === "idle" || state.status === "loading") && <p className="text-sm text-gray-700">Loading feedback…</p>}
      {state.status === "error" && <p role="alert" className="text-sm text-red-800">Couldn&apos;t load feedback: {state.message}</p>}
      {state.status === "ready" && (
        <>
          <div aria-live="polite">
            {state.feedback.status === "failed" ? (
              <FeedbackFailed submissionId={submission.id} onRetried={() => setRestart((n) => n + 1)} />
            ) : state.feedback.status !== "released" && (
              <p className="text-sm text-gray-800">
                {FEEDBACK_STATUS_TEXT[state.feedback.status]}
                {feedbackStillOpen(state.feedback.status) ? ". This page checks again automatically." : "."}
              </p>
            )}
          </div>
          {state.feedback.criteria.length > 0 && <CriterionFeedbackList criteria={state.feedback.criteria} headingLevel={4} />}
          {state.feedback.practice_set_ai_action_id && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3">
              <Link
                href={`/course/${courseId}/practice/${state.feedback.practice_set_ai_action_id}`}
                className="inline-flex min-h-6 items-center gap-1 text-sm font-semibold text-indigo-900 underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
              >
                <Dumbbell aria-hidden="true" className="h-4 w-4" />
                Practice for this
              </Link>
              <p className="text-xs text-indigo-950">A short practice set aimed at the criterion you&apos;re working on. Your attempts are private.</p>
              <AiGeneratedLabel aiActionId={state.feedback.practice_set_ai_action_id} />
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FeedbackFailed({ submissionId, onRetried }: { submissionId: string; onRetried: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retry = async () => {
    setBusy(true);
    setError(null);
    const problem = await retryFeedback(submissionId);
    setBusy(false);
    if (problem) setError(problem);
    else onRetried();
  };
  return (
    <div className="space-y-2 rounded-lg border border-red-300 bg-red-50 p-3">
      <p className="flex items-start gap-1 text-sm text-red-900">
        <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
        <span><span className="font-semibold">Error:</span> {FEEDBACK_STATUS_TEXT.failed}. Your submission is saved.</span>
      </p>
      {error && <p role="alert" className="text-sm text-red-900">Retry failed: {error}</p>}
      <button
        type="button"
        onClick={retry}
        disabled={busy}
        className="inline-flex min-h-6 items-center gap-1 rounded border border-gray-500 bg-white px-3 py-1 text-sm font-medium text-gray-900 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
      >
        <RotateCw aria-hidden="true" className="h-4 w-4" />
        {busy ? "Retrying…" : "Retry feedback"}
      </button>
    </div>
  );
}
