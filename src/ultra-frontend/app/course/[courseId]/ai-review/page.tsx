"use client";

import { use, useCallback, useEffect, useId, useState } from "react";
import Link from "next/link";
import { Download } from "lucide-react";
import { ApiError, apiFetch, apiJson } from "@/lib/api";
import { SCOPE_COURSE_ID, useAuth } from "@/lib/auth-context";
import { aiReviewAllowed } from "@/components/CourseTabs";
import { NoAccess } from "@/components/NoAccess";
import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";
import type { AiAction, MeasurementRollup, MeasurementSummary } from "@/lib/types";
import { MeasurementView, RatesTable } from "./MeasurementView";
import { dateParam, humanize } from "./format";

interface Range { from: string; to: string }

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

function rangeQuery(range: Range): URLSearchParams {
  const q = new URLSearchParams();
  const from = dateParam(range.from, false);
  const to = dateParam(range.to, true);
  if (from) q.set("from", from);
  if (to) q.set("to", to);
  return q;
}

function useMeasurement<T>(path: string | null): [Load<T>, () => void] {
  const [state, setState] = useState<Load<T>>({ status: "loading" });
  const load = useCallback(() => {
    if (!path) return;
    setState({ status: "loading" });
    apiJson<T>(path)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        // 403 has already switched the page to the no-access state.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return;
        setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
  }, [path]);
  useEffect(load, [load]);
  return [state, load];
}

export default function AiReviewPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { capabilities, findEnrollment } = useAuth();
  const isScope = courseId === SCOPE_COURSE_ID;
  const [range, setRange] = useState<Range>({ from: "", to: "" });

  if (!aiReviewAllowed(capabilities, isScope ? null : findEnrollment(courseId), isScope)) return <NoAccess />;

  return (
    <div className="max-w-6xl space-y-4 p-6">
      <div>
        <h2 className="text-lg font-semibold">{isScope ? "AI Review — institution" : "AI Review"}</h2>
        <p className="text-sm text-gray-600">
          What the software generated, what instructors did with it, and what happened to learning afterward.
        </p>
      </div>
      <RangeForm range={range} onApply={setRange} />
      {isScope ? <RollupReview range={range} /> : <CourseReview courseId={courseId} range={range} />}
    </div>
  );
}

function RangeForm({ range, onApply }: { range: Range; onApply: (r: Range) => void }) {
  const [draft, setDraft] = useState(range);
  const fromId = useId();
  const toId = useId();
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-xl border border-gray-200 bg-white p-3"
      onSubmit={(e) => { e.preventDefault(); onApply(draft); }}
      aria-label="Date range"
    >
      <div>
        <label htmlFor={fromId} className="block text-xs font-medium text-gray-700">From</label>
        <input id={fromId} type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          className="rounded border border-gray-300 px-2 py-1 text-sm" />
      </div>
      <div>
        <label htmlFor={toId} className="block text-xs font-medium text-gray-700">To (inclusive)</label>
        <input id={toId} type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          className="rounded border border-gray-300 px-2 py-1 text-sm" />
      </div>
      <button type="submit" className="rounded bg-[#1a1a1a] px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]">
        Apply
      </button>
    </form>
  );
}

function LoadState<T>({ state, retry, children }: { state: Load<T>; retry: () => void; children: (data: T) => React.ReactNode }) {
  if (state.status === "loading") return <p role="status" className="text-sm text-gray-600">Loading AI Review…</p>;
  if (state.status === "error") {
    return (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        <p>Couldn&apos;t load AI Review: {state.message}</p>
        <button type="button" onClick={retry} className="mt-2 rounded border border-red-300 bg-white px-3 py-1 text-sm font-medium">Try again</button>
      </div>
    );
  }
  return <>{children(state.data)}</>;
}

function CourseReview({ courseId, range }: { courseId: string; range: Range }) {
  const q = rangeQuery(range).toString();
  const [state, retry] = useMeasurement<MeasurementSummary>(
    `/api/measurement/courses/${encodeURIComponent(courseId)}${q ? `?${q}` : ""}`,
  );
  return (
    <>
      <ExportControls courseId={courseId} range={range} />
      <LoadState state={state} retry={retry}>{(s) => <MeasurementView summary={s} />}</LoadState>
      <RecentActions courseId={courseId} range={range} />
    </>
  );
}

function RollupReview({ range }: { range: Range }) {
  const q = rangeQuery(range).toString();
  const [state, retry] = useMeasurement<MeasurementRollup>(`/api/measurement/rollup${q ? `?${q}` : ""}`);
  return (
    <LoadState state={state} retry={retry}>
      {(r) => (
        <div className="space-y-4">
          <section aria-labelledby="ai-review-compliance" className="rounded-xl border border-gray-200 bg-white p-4">
            <h3 id="ai-review-compliance" className="text-sm font-semibold">Policy compliance</h3>
            <p className="text-sm text-gray-700">
              {r.compliance.mismatches_count === 0
                ? "No recorded mismatches between applied and effective policy."
                : `${r.compliance.mismatches_count} recorded mismatches between applied and effective policy.`}
            </p>
          </section>
          <MeasurementView summary={r} />
          <section aria-labelledby="ai-review-per-course" className="rounded-xl border border-gray-200 bg-white p-4">
            <h3 id="ai-review-per-course" className="mb-3 text-sm font-semibold">By course</h3>
            {r.per_course.length === 0 ? <p className="text-sm text-gray-600">No courses with generated items.</p> : (
              <>
                <RatesTable
                  rows={r.per_course.map((c) => c.totals)}
                  rowHeader="Course"
                  rowLabel={(_, i) => r.per_course[i].course.title}
                  caption="Decision counts and rates per course"
                />
                <ul className="mt-3 flex flex-wrap gap-3 text-sm">
                  {r.per_course.map((c) => (
                    <li key={c.course.course_id}>
                      <Link href={`/course/${c.course.course_id}/ai-review`} className="text-[#1a56db] underline">
                        Open AI Review for {c.course.title}
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>
      )}
    </LoadState>
  );
}

const RECENT_LIMIT = 10;

function RecentActions({ courseId, range }: { courseId: string; range: Range }) {
  const q = rangeQuery(range);
  q.set("course_id", courseId);
  q.set("limit", String(RECENT_LIMIT));
  const [state, retry] = useMeasurement<{ items: AiAction[] }>(`/api/ai-actions?${q.toString()}`);
  return (
    <section aria-labelledby="ai-review-recent" className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 id="ai-review-recent" className="mb-3 text-sm font-semibold">Recent generated items</h3>
      <LoadState state={state} retry={retry}>
        {({ items }) => items.length === 0 ? <p className="text-sm text-gray-600">No generated items in this period.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">The {RECENT_LIMIT} most recent generated items in this course, newest first</caption>
              <thead>
                <tr>
                  <th scope="col" className="border-b border-gray-200 px-3 py-2 text-left text-xs font-semibold text-gray-700">Created</th>
                  <th scope="col" className="border-b border-gray-200 px-3 py-2 text-left text-xs font-semibold text-gray-700">Agent</th>
                  <th scope="col" className="border-b border-gray-200 px-3 py-2 text-left text-xs font-semibold text-gray-700">Action type</th>
                  <th scope="col" className="border-b border-gray-200 px-3 py-2 text-left text-xs font-semibold text-gray-700">Latest decision</th>
                  <th scope="col" className="border-b border-gray-200 px-3 py-2 text-left text-xs font-semibold text-gray-700">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.id} className="align-top">
                    <td className="border-b border-gray-100 px-3 py-2">{new Date(a.created_at).toLocaleString()}</td>
                    <td className="border-b border-gray-100 px-3 py-2">{a.agent}</td>
                    <td className="border-b border-gray-100 px-3 py-2">{humanize(a.action_type)}</td>
                    <td className="border-b border-gray-100 px-3 py-2">{a.decisions.at(-1)?.decision ?? "none yet"}</td>
                    <td className="border-b border-gray-100 px-3 py-2"><AiGeneratedLabel aiActionId={a.id} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  );
}

const EXPORTS = [
  { label: "JSON (all tables)", format: "json", table: null },
  { label: "CSV: generated items", format: "csv", table: "ai_actions" },
  { label: "CSV: decisions", format: "csv", table: "human_decisions" },
  { label: "CSV: outcomes", format: "csv", table: "outcome_links" },
] as const;

function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition && /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return match ? decodeURIComponent(match[1]) : fallback;
}

function ExportControls({ courseId, range }: { courseId: string; range: Range }) {
  const [status, setStatus] = useState<string>("");

  const download = async (format: "json" | "csv", table: string | null) => {
    const q = rangeQuery(range);
    q.set("course_id", courseId);
    q.set("format", format);
    if (table) q.set("table", table);
    setStatus("Preparing export…");
    try {
      const res = await apiFetch(`/api/measurement/export?${q.toString()}`);
      if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`.trim());
      const blob = await res.blob();
      const name = filenameFrom(res.headers.get("content-disposition"), `ai-review-${table ?? "export"}.${format}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
      setStatus(`Downloaded ${name}.`);
    } catch (err: unknown) {
      setStatus(`Export failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <section aria-labelledby="ai-review-export" className="rounded-xl border border-gray-200 bg-white p-3">
      <h3 id="ai-review-export" className="mb-2 text-sm font-semibold">Export for evaluators</h3>
      <div className="flex flex-wrap gap-2">
        {EXPORTS.map((e) => (
          <button
            key={e.label}
            type="button"
            onClick={() => download(e.format, e.table)}
            className="inline-flex items-center gap-1.5 rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-900 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
          >
            <Download aria-hidden="true" className="h-4 w-4" />
            {e.label}
          </button>
        ))}
      </div>
      <p role="status" className="mt-2 text-xs text-gray-700">{status}</p>
    </section>
  );
}
