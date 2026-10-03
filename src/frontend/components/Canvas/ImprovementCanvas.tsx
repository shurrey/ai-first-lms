"use client";

import { useId, useState } from "react";
import { ArrowDown, ArrowUp, CheckCircle2, Minus } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { useApiGet } from "@/lib/use-api";
import {
  FLAG_LABELS,
  type CriterionTrajectory,
  type Improvement,
  type TrajectoryFlag,
} from "@/lib/assessment";
import { FeedbackCanvas } from "./FeedbackCanvas";

function humanKey(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function FlagText({ flag }: { flag: TrajectoryFlag | null }) {
  if (!flag) return null;
  const Icon =
    flag === "improving" ? ArrowUp : flag === "regressed" ? ArrowDown : flag === "ready_for_summative" ? CheckCircle2 : Minus;
  return (
    <span className="inline-flex items-center gap-0.5 rounded border border-border bg-background px-1 text-[11px] font-medium">
      <Icon aria-hidden="true" className="h-3 w-3" />
      {FLAG_LABELS[flag]}
    </span>
  );
}

function trajectoryText(t: CriterionTrajectory | undefined): string {
  if (!t || t.points.length === 0) return "No scores";
  return t.points.map((p) => (p.score == null ? "–" : String(p.score))).join(" → ");
}

interface Selection {
  studentName: string;
  criterionKey: string;
  trajectory: CriterionTrajectory;
}

/**
 * Student × criterion improvement grid for one course (spec §7.7). Built only from
 * course-visibility evidence, so private practice never appears (§12.5). Aggregate-only
 * callers get per-criterion flag counts instead of student rows.
 */
export function ImprovementCanvas({ courseId }: { courseId: string }) {
  const { me } = useAuth();
  const { data, loading, error, forbidden } = useApiGet<Improvement>(
    `/api/improvement/${encodeURIComponent(courseId)}`
  );
  const [selected, setSelected] = useState<Selection | null>(null);
  const [feedbackFor, setFeedbackFor] = useState<string | null>(null);
  const headingId = useId();
  const isStudent = me.active_role === "student";
  // Advisors see scores only; criterion feedback belongs to the student and their instructors.
  const canReadFeedback = isStudent || me.capabilities.feedback_release !== undefined;

  let body: React.ReactNode;
  if (loading) body = <p role="status">Loading improvement…</p>;
  else if (forbidden) body = <p role="alert">Your role can&apos;t view improvement for this course.</p>;
  else if (error || !data) body = <p role="alert">Couldn&apos;t load improvement. Please try again.</p>;
  else if (data.criteria.length === 0) body = <p className="text-xs text-muted-foreground">No rubric criteria are set up for this course yet.</p>;
  else {
    body = (
      <>
        {data.students.length > 0 ? (
          <Grid data={data} onSelect={(s) => { setSelected(s); setFeedbackFor(null); }} />
        ) : (
          <Aggregate data={data} />
        )}
        {selected && (
          <DrillDown
            selection={selected}
            feedbackFor={feedbackFor}
            onOpenFeedback={canReadFeedback ? setFeedbackFor : null}
            onClose={() => { setSelected(null); setFeedbackFor(null); }}
          />
        )}
      </>
    );
  }

  return (
    <section aria-labelledby={headingId} className="space-y-3 text-sm" data-testid="improvement-canvas">
      <h2 id={headingId} className="text-base font-semibold">
        {isStudent ? "My improvement" : "Improvement"}
      </h2>
      <p className="text-xs text-muted-foreground">
        Scores per rubric criterion across drafts, revisions and finals. Practice attempts are private
        to each student and are not included.
      </p>
      {body}
    </section>
  );
}

function Grid({
  data,
  onSelect,
}: {
  data: Improvement;
  onSelect: (s: Selection) => void;
}) {
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Improvement grid">
      <table className="w-full border-collapse text-xs">
        <caption className="sr-only">
          Score trajectory per student and criterion. Select a cell to see each version.
        </caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="px-2 py-1 text-left font-medium">
              Student
            </th>
            {data.criteria.map((c) => (
              <th key={c.criterion_id} scope="col" className="px-2 py-1 text-left font-medium">
                {humanKey(c.criterion_key)}
                {c.target_score != null && (
                  <span className="block font-normal text-muted-foreground">target {c.target_score}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.students.map((s) => (
            <tr key={s.student_id} className="border-b border-border/50 align-top">
              <th scope="row" className="px-2 py-1 text-left font-normal">
                {s.display_name}
              </th>
              {data.criteria.map((c) => {
                const t = s.trajectories.find((x) => x.criterion_id === c.criterion_id);
                return (
                  <td key={c.criterion_id} className="px-1 py-1">
                    {t && t.points.length > 0 ? (
                      <button
                        type="button"
                        onClick={() => onSelect({ studentName: s.display_name, criterionKey: c.criterion_key, trajectory: t })}
                        className="flex min-h-6 w-full flex-col items-start gap-0.5 rounded px-1 py-0.5 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                      >
                        <span className="tabular-nums">
                          {trajectoryText(t)}
                          <span className="sr-only">
                            {" "}for {s.display_name}, {humanKey(c.criterion_key)}
                          </span>
                        </span>
                        <FlagText flag={t.flag} />
                      </button>
                    ) : (
                      <span className="px-1 text-muted-foreground">No scores</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Aggregate({ data }: { data: Improvement }) {
  const rows = data.aggregate ?? [];
  const flags = Object.keys(FLAG_LABELS) as TrajectoryFlag[];
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Improvement across students">
      <table className="w-full border-collapse text-xs">
        <caption className="mb-1 text-left text-sm font-semibold">Across students</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="px-2 py-1 text-left font-medium">Criterion</th>
            <th scope="col" className="px-2 py-1 text-right font-medium">Students</th>
            <th scope="col" className="px-2 py-1 text-right font-medium">Mean change</th>
            {flags.map((f) => (
              <th key={f} scope="col" className="px-2 py-1 text-right font-medium">{FLAG_LABELS[f]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={3 + flags.length} className="px-2 py-2 text-muted-foreground">No trajectories yet.</td>
            </tr>
          ) : (
            rows.map((r) => {
              const c = data.criteria.find((x) => x.criterion_id === r.criterion_id);
              return (
                <tr key={r.criterion_id} className="border-b border-border/50">
                  <th scope="row" className="px-2 py-1 text-left font-normal">{humanKey(c?.criterion_key ?? r.criterion_id)}</th>
                  <td className="px-2 py-1 text-right tabular-nums">{r.n_students}</td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    {r.mean_delta == null ? "–" : `${r.mean_delta > 0 ? "+" : ""}${r.mean_delta.toFixed(2)}`}
                  </td>
                  {flags.map((f) => (
                    <td key={f} className="px-2 py-1 text-right tabular-nums">{r.flag_counts[f] ?? 0}</td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function DrillDown({
  selection,
  feedbackFor,
  onOpenFeedback,
  onClose,
}: {
  selection: Selection;
  feedbackFor: string | null;
  onOpenFeedback: ((submissionId: string) => void) | null;
  onClose: () => void;
}) {
  const headingId = useId();
  const { trajectory: t } = selection;
  return (
    <section aria-labelledby={headingId} className="space-y-2 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-sm font-semibold">
          {selection.studentName} · {humanKey(selection.criterionKey)}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="min-h-6 rounded-md border border-border bg-background px-2 py-0.5 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          Close details
        </button>
      </div>
      <p className="text-xs">
        {t.latest_delta == null
          ? "One version so far."
          : `Latest change: ${t.latest_delta > 0 ? "+" : ""}${t.latest_delta}.`}{" "}
        <FlagText flag={t.flag} />
      </p>
      <ol className="space-y-1 text-xs">
        {t.points.map((p) => (
          <li key={p.submission_id} className="flex flex-wrap items-center gap-2">
            <span>
              Version {p.version} ({p.status}) · {new Date(p.submitted_at).toLocaleDateString()} · Level{" "}
              {p.score ?? "–"}
            </span>
            {onOpenFeedback && <button
              type="button"
              aria-expanded={feedbackFor === p.submission_id}
              onClick={() => onOpenFeedback(p.submission_id)}
              className="min-h-6 rounded-md border border-border bg-background px-2 py-0.5 hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              View feedback<span className="sr-only"> for version {p.version}</span>
            </button>}
          </li>
        ))}
      </ol>
      {feedbackFor && onOpenFeedback && <FeedbackCanvas key={feedbackFor} submissionId={feedbackFor} />}
    </section>
  );
}
