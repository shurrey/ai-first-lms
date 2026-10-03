"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, LineChart } from "lucide-react";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useSession } from "@/lib/session-context";
import { useApiGet } from "@/lib/use-api";
import { toPracticeSet, type FeedbackStatus, type Submission, type SubmissionFeedback } from "@/lib/assessment";
import type { AiAction } from "@/lib/provenance";
import { CanvasDialog } from "@/components/common/CanvasDialog";
import { FeedbackCanvas } from "@/components/Canvas/FeedbackCanvas";
import { ImprovementCanvas } from "@/components/Canvas/ImprovementCanvas";
import { PracticeSetCanvas } from "@/components/Canvas/PracticeSetCanvas";
import { SectionLabel } from "./shared";

type Open =
  | { kind: "feedback"; id: string }
  | { kind: "practice"; id: string }
  | { kind: "improvement"; courseId: string }
  | null;

// The queue changes outside any turn this person streams, so it is polled.
const QUEUE_POLL_MS = 60000;

const DIALOG_LABEL = { feedback: "Feedback", practice: "Practice", improvement: "Improvement" } as const;

const STUDENT_STATUS: Record<FeedbackStatus, string> = {
  pending: "feedback in progress",
  awaiting_release: "awaiting instructor release",
  released: "feedback ready",
  suppressed: "no feedback released",
  failed: "feedback failed, open to retry",
  none: "final",
};

const rowButton =
  "flex min-h-6 w-full items-center justify-between gap-2 rounded px-1 py-1 text-left text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

/** Formative-loop entry points in the CoursePanel, each shown only to roles that can use it. */
export function AssessmentPanel() {
  const { me } = useAuth();
  const { courseUuid } = useSession();
  const [open, setOpen] = useState<Open>(null);
  const caps = me.capabilities;
  const isStudent = me.active_role === "student";
  const courseId = courseUuid && courseUuid !== "all" ? courseUuid : null;

  const showQueue = caps.feedback_release !== undefined;
  const showImprovement = caps.improvement_view !== undefined && courseId !== null;
  const showMine = isStudent && caps.submit_work !== undefined && courseId !== null;
  const showPractice = isStudent && caps.ai_actions_log !== undefined && courseId !== null;
  if (!showQueue && !showImprovement && !showMine && !showPractice) return null;

  return (
    <div className="mb-4 space-y-4">
      {showQueue && <ReviewQueue courseId={courseId} onOpen={(id) => setOpen({ kind: "feedback", id })} />}
      {showMine && <MySubmissions courseId={courseId} onOpen={(id) => setOpen({ kind: "feedback", id })} />}
      {showPractice && <MyPractice courseId={courseId} onOpen={(id) => setOpen({ kind: "practice", id })} />}
      {showImprovement && (
        <button
          type="button"
          onClick={() => setOpen({ kind: "improvement", courseId })}
          className="inline-flex min-h-6 w-full items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <LineChart aria-hidden="true" className="h-3.5 w-3.5" />
          {isStudent ? "Open my improvement" : "Open Improvement"}
        </button>
      )}
      <CanvasDialog open={open !== null} onClose={() => setOpen(null)} label={open ? DIALOG_LABEL[open.kind] : "Canvas"}>
        {open?.kind === "feedback" && (
          <FeedbackCanvas
            key={open.id}
            submissionId={open.id}
            onOpenPractice={(id) => setOpen({ kind: "practice", id })}
          />
        )}
        {open?.kind === "practice" && <PracticeSetCanvas key={open.id} aiActionId={open.id} />}
        {open?.kind === "improvement" && <ImprovementCanvas courseId={open.courseId} />}
      </CanvasDialog>
    </div>
  );
}

function ReviewQueue({ courseId, onOpen }: { courseId: string | null; onOpen: (id: string) => void }) {
  const path = courseId ? `/api/feedback/queue?course_id=${encodeURIComponent(courseId)}` : "/api/feedback/queue";
  const q = useQuery({
    queryKey: ["api", path],
    queryFn: () => apiJson<{ items: SubmissionFeedback[] }>(path),
    retry: false,
    refetchInterval: QUEUE_POLL_MS,
  });
  const items = q.data?.items ?? [];
  return (
    <section aria-label="Review queue">
      <SectionLabel>Feedback awaiting release{q.data ? ` (${items.length})` : ""}</SectionLabel>
      <div className="rounded-lg border border-border bg-card p-2">
        {q.isPending ? (
          <p role="status" className="text-xs">Loading review queue…</p>
        ) : q.isError ? (
          <p role="alert" className="text-xs">Couldn&apos;t load the review queue.</p>
        ) : items.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nothing is waiting for you.</p>
        ) : (
          <ul className="space-y-0.5">
            {items.map((f) => (
              <li key={f.submission_id}>
                <button type="button" onClick={() => onOpen(f.submission_id)} className={rowButton}>
                  <span className="inline-flex items-center gap-1 truncate">
                    <ClipboardCheck aria-hidden="true" className="h-3 w-3 shrink-0" />
                    {f.student_name ?? "Student"}
                  </span>
                  <span className="shrink-0 text-muted-foreground">
                    {f.criteria.length} criteri{f.criteria.length === 1 ? "on" : "a"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function MySubmissions({ courseId, onOpen }: { courseId: string; onOpen: (id: string) => void }) {
  const q = useApiGet<{ items: Submission[] }>(`/api/submissions?course_id=${encodeURIComponent(courseId)}`);
  const items = q.data?.items ?? [];
  if (q.loading || q.error || items.length === 0) return null;
  return (
    <section aria-label="My feedback">
      <SectionLabel>My feedback</SectionLabel>
      <ul className="space-y-0.5 rounded-lg border border-border bg-card p-2">
        {items.map((s) => (
          <li key={s.id}>
            <button type="button" onClick={() => onOpen(s.id)} className={rowButton}>
              <span className="truncate">
                {s.assignment_title ? `${s.assignment_title}, version` : "Version"} {s.version} ({s.status})
              </span>
              <span className="shrink-0 text-muted-foreground">
                {STUDENT_STATUS[s.feedback_status ?? "pending"]}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MyPractice({ courseId, onOpen }: { courseId: string; onOpen: (id: string) => void }) {
  const q = useApiGet<{ items: AiAction[] }>(
    `/api/ai-actions?action_type=practice_item&course_id=${encodeURIComponent(courseId)}`
  );
  const sets = (q.data?.items ?? []).map(toPracticeSet);
  if (q.loading || q.error || sets.length === 0) return null;
  return (
    <section aria-label="My practice">
      <SectionLabel>My practice (private)</SectionLabel>
      <ul className="space-y-0.5 rounded-lg border border-border bg-card p-2">
        {sets.map((s) => (
          <li key={s.ai_action_id}>
            <button type="button" onClick={() => onOpen(s.ai_action_id)} className={rowButton}>
              <span className="truncate">{s.title}</span>
              <span className="shrink-0 text-muted-foreground">
                {s.items.length} item{s.items.length === 1 ? "" : "s"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
