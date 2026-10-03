"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { FLAG_LABELS, formatDateTime, humanizeKey } from "@/lib/assessment";
import { useFeedbackPoll } from "@/lib/use-feedback";
import { NoAccess } from "@/components/NoAccess";
import { ChangeIndicator } from "@/components/assessment/ChangeIndicator";
import { CriterionFeedbackList } from "@/components/assessment/CriterionFeedbackList";
import { FlagLabel } from "@/components/assessment/FlagLabel";
import type { CriterionTrajectory, Improvement, TrajectoryFlag } from "@/lib/types";

type Load = { status: "loading" } | { status: "ready"; data: Improvement } | { status: "error"; message: string };

interface Selection { studentName: string; criterionKey: string; trajectory: CriterionTrajectory }

export default function ImprovementPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { activeRole, capabilities } = useAuth();
  if (!capabilities.improvement_view) return <NoAccess />;
  return <ImprovementView courseId={courseId} canReadFeedback={activeRole === "student" || !!capabilities.feedback_release} />;
}

/** Summary roles (advisors) see scores only: criterion feedback, drafts included, belongs to the student and their instructors. */
function ImprovementView({ courseId, canReadFeedback }: { courseId: string; canReadFeedback: boolean }) {
  const [state, setState] = useState<Load>({ status: "loading" });
  const [selection, setSelection] = useState<Selection | null>(null);

  const load = useCallback(() => {
    setState({ status: "loading" });
    apiJson<Improvement>(`/api/improvement/${encodeURIComponent(courseId)}`)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return;
        setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
  }, [courseId]);
  useEffect(load, [load]);

  return (
    <div className="max-w-6xl space-y-4 p-6">
      <div>
        <h2 className="text-lg font-semibold">Improvement</h2>
        <p className="text-sm text-gray-700">
          Criterion scores across each student&apos;s drafts, revisions and final. Private practice attempts are not included.
        </p>
      </div>
      {state.status === "loading" && <p role="status" className="text-sm text-gray-700">Loading improvement…</p>}
      {state.status === "error" && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Couldn&apos;t load improvement: {state.message}
          <button type="button" onClick={load} className="ml-2 min-h-6 rounded border border-red-300 bg-white px-3 py-1 text-sm font-medium">Try again</button>
        </div>
      )}
      {state.status === "ready" && (
        state.data.students.length > 0
          ? <TrajectoryGrid data={state.data} onSelect={setSelection} />
          : <AggregateTable data={state.data} />
      )}
      {selection && <DrillDown selection={selection} canReadFeedback={canReadFeedback} onClose={() => setSelection(null)} />}
    </div>
  );
}

function scoresText(t: CriterionTrajectory | undefined): string {
  if (!t || t.points.length === 0) return "No submissions";
  return t.points.map((p) => (p.score == null ? "–" : String(p.score))).join(" → ");
}

function TrajectoryGrid({ data, onSelect }: { data: Improvement; onSelect: (s: Selection) => void }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <caption className="sr-only">Student by criterion trajectories. Each cell lists scores from first to latest version, the latest change and a flag.</caption>
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th scope="col" className="px-3 py-2 font-semibold">Student</th>
            {data.criteria.map((c) => (
              <th key={c.criterion_id} scope="col" className="px-3 py-2 font-semibold">
                {humanizeKey(c.criterion_key)}
                {c.target_score != null && <span className="block text-xs font-normal text-gray-700">target {c.target_score}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.students.map((s) => (
            <tr key={s.student_id} className="border-b border-gray-100 align-top">
              <th scope="row" className="px-3 py-2 text-left font-medium">{s.display_name}</th>
              {data.criteria.map((c) => {
                const t = s.trajectories.find((x) => x.criterion_id === c.criterion_id);
                return (
                  <td key={c.criterion_id} className="px-3 py-2">
                    {t && t.points.length > 0 ? (
                      <button
                        type="button"
                        onClick={() => onSelect({ studentName: s.display_name, criterionKey: c.criterion_key, trajectory: t })}
                        aria-label={`${s.display_name}, ${humanizeKey(c.criterion_key)}: ${scoresText(t)}${t.flag ? `, ${FLAG_LABELS[t.flag]}` : ""}. Show submissions`}
                        className="min-h-6 rounded text-left underline decoration-dotted underline-offset-2 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
                      >
                        <span className="block font-medium">{scoresText(t)}</span>
                      </button>
                    ) : <span className="text-gray-700">No submissions</span>}
                    {t && t.points.length > 1 && <span className="mt-1 block"><ChangeIndicator delta={t.latest_delta} /></span>}
                    {t?.flag && <span className="mt-1 block"><FlagLabel flag={t.flag} /></span>}
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

function AggregateTable({ data }: { data: Improvement }) {
  const rows = data.aggregate ?? [];
  if (rows.length === 0) return <p className="text-sm text-gray-700">No submissions with released feedback yet.</p>;
  const name = (id: string) => humanizeKey(data.criteria.find((c) => c.criterion_id === id)?.criterion_key ?? id);
  const flags = Object.keys(FLAG_LABELS) as TrajectoryFlag[];
  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <caption className="px-3 pt-3 text-left text-sm text-gray-800">Aggregate across students; individual students are not shown for your role.</caption>
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th scope="col" className="px-3 py-2">Criterion</th>
            <th scope="col" className="px-3 py-2">Students</th>
            <th scope="col" className="px-3 py-2">Mean change</th>
            {flags.map((f) => <th key={f} scope="col" className="px-3 py-2">{FLAG_LABELS[f]}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.criterion_id} className="border-b border-gray-100">
              <th scope="row" className="px-3 py-2 text-left font-medium">{name(r.criterion_id)}</th>
              <td className="px-3 py-2">{r.n_students}</td>
              <td className="px-3 py-2">{r.mean_delta == null ? "n/a" : r.mean_delta.toFixed(2)}</td>
              {flags.map((f) => <td key={f} className="px-3 py-2">{r.flag_counts[f] ?? 0}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DrillDown({ selection, canReadFeedback, onClose }: { selection: Selection; canReadFeedback: boolean; onClose: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [submissionId, setSubmissionId] = useState<string | null>(null);
  const { trajectory } = selection;
  useEffect(() => {
    headingRef.current?.focus();
    setSubmissionId(null);
  }, [selection]);

  return (
    <section aria-labelledby="drilldown-heading" className="rounded-xl border border-gray-300 bg-white p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 id="drilldown-heading" ref={headingRef} tabIndex={-1} className="text-base font-semibold outline-none">
          {selection.studentName} · {humanizeKey(selection.criterionKey)}
        </h3>
        <button type="button" onClick={onClose} aria-label="Close submissions" className="min-h-6 min-w-6 rounded p-1 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]">
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
      {trajectory.flag && <p className="mt-1"><FlagLabel flag={trajectory.flag} /></p>}
      <table className="mt-3 w-full text-sm">
        <caption className="sr-only">Submissions for this criterion, oldest first</caption>
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th scope="col" className="py-1 pr-3">Version</th>
            <th scope="col" className="py-1 pr-3">Status</th>
            <th scope="col" className="py-1 pr-3">Score</th>
            <th scope="col" className="py-1 pr-3">Change</th>
            <th scope="col" className="py-1 pr-3">Submitted</th>
            {canReadFeedback && <th scope="col" className="py-1"><span className="sr-only">Feedback</span></th>}
          </tr>
        </thead>
        <tbody>
          {trajectory.points.map((p, i) => {
            const prev = i > 0 ? trajectory.points[i - 1].score : null;
            const delta = i > 0 && p.score != null && prev != null ? p.score - prev : null;
            return (
              <tr key={p.submission_id} className="border-b border-gray-100">
                <td className="py-1 pr-3">{p.version}</td>
                <td className="py-1 pr-3">{p.status}</td>
                <td className="py-1 pr-3">{p.score ?? "–"}</td>
                <td className="py-1 pr-3"><ChangeIndicator delta={delta} isFirst={i === 0} /></td>
                <td className="py-1 pr-3">{formatDateTime(p.submitted_at)}</td>
                {canReadFeedback && <td className="py-1">
                  <button
                    type="button"
                    onClick={() => setSubmissionId(p.submission_id)}
                    aria-pressed={submissionId === p.submission_id}
                    className="min-h-6 text-[#1a5fb4] underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
                  >
                    Feedback for version {p.version}
                  </button>
                </td>}
              </tr>
            );
          })}
        </tbody>
      </table>
      {submissionId && <SubmissionFeedbackDetail submissionId={submissionId} />}
    </section>
  );
}

function SubmissionFeedbackDetail({ submissionId }: { submissionId: string }) {
  const state = useFeedbackPoll(submissionId);
  return (
    <div className="mt-3" aria-live="polite">
      {(state.status === "loading" || state.status === "idle") && <p className="text-sm text-gray-700">Loading feedback…</p>}
      {state.status === "error" && <p role="alert" className="text-sm text-red-800">Couldn&apos;t load feedback: {state.message}</p>}
      {state.status === "ready" && (
        state.feedback.criteria.length === 0
          ? <p className="text-sm text-gray-700">No criterion feedback on this version.</p>
          : <CriterionFeedbackList criteria={state.feedback.criteria} headingLevel={4} />
      )}
    </div>
  );
}
