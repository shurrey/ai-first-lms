"use client";

import { Suspense, use, useCallback, useEffect, useId, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { canReadAccessLog, formatDateTime } from "@/lib/assessment";
import { dateParam } from "@/app/course/[courseId]/ai-review/format";
import { NoAccess } from "@/components/NoAccess";
import type { AccessLogEntry, AccessLogPage, AccessLogResource } from "@/lib/types";

const RESOURCE_LABELS: Record<AccessLogResource, string> = {
  transcript: "Tutor transcript",
  profile: "Learner profile",
  analyst_summary: "Analyst summary",
  submission: "Submission",
};

interface Filters { resource: "" | AccessLogResource; from: string; to: string }

type Load =
  | { status: "loading" }
  | { status: "ready"; entries: AccessLogEntry[]; nextBefore: string | null; loadingMore: boolean }
  | { status: "error"; message: string };

export default function AccessLogRoute({ params }: { params: Promise<{ personId: string }> }) {
  const { personId } = use(params);
  const { capabilities } = useAuth();
  if (!canReadAccessLog(capabilities)) return <NoAccess />;
  return (
    <Suspense fallback={<p role="status" className="p-6 text-sm text-gray-700">Loading…</p>}>
      <AccessLog subjectId={personId} />
    </Suspense>
  );
}

function query(subjectId: string, f: Filters, before: string | null): string {
  const q = new URLSearchParams({ subject_id: subjectId });
  if (f.resource) q.set("resource", f.resource);
  const from = dateParam(f.from, false);
  const to = dateParam(f.to, true);
  if (from) q.set("from", from);
  if (to) q.set("to", to);
  if (before) q.set("before", before);
  return q.toString();
}

function AccessLog({ subjectId }: { subjectId: string }) {
  const name = useSearchParams().get("name");
  const [filters, setFilters] = useState<Filters>({ resource: "", from: "", to: "" });
  const [state, setState] = useState<Load>({ status: "loading" });
  const [announcement, setAnnouncement] = useState("");

  const fail = (err: unknown) => {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return;
    setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
  };

  const load = useCallback(() => {
    setState({ status: "loading" });
    apiJson<AccessLogPage>(`/api/access-log?${query(subjectId, filters, null)}`)
      .then((p) => {
        setState({ status: "ready", entries: p.entries, nextBefore: p.next_before, loadingMore: false });
        setAnnouncement(`${p.entries.length} entries shown.`);
      })
      .catch(fail);
  }, [subjectId, filters]);
  useEffect(load, [load]);

  const loadMore = () => {
    if (state.status !== "ready" || !state.nextBefore) return;
    const shown = state.entries;
    setState({ ...state, loadingMore: true });
    apiJson<AccessLogPage>(`/api/access-log?${query(subjectId, filters, state.nextBefore)}`)
      .then((p) => {
        setState({ status: "ready", entries: [...shown, ...p.entries], nextBefore: p.next_before, loadingMore: false });
        setAnnouncement(`${p.entries.length} older entries loaded.`);
      })
      .catch(fail);
  };

  return (
    <div className="max-w-5xl space-y-4 p-6">
      <div role="status" aria-live="polite" className="sr-only">{announcement}</div>
      <div>
        <h1 className="text-xl font-semibold">Data access log{name ? `: ${name}` : ""}</h1>
        <p className="text-sm text-gray-700">
          Who read this learner&apos;s transcripts, profile, analyst summaries or submissions, newest first.
        </p>
      </div>
      <FilterForm value={filters} onApply={setFilters} />
      {state.status === "loading" && <p className="text-sm text-gray-700">Loading entries…</p>}
      {state.status === "error" && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Couldn&apos;t load the access log: {state.message}
          <button type="button" onClick={load} className="ml-2 min-h-6 rounded border border-red-300 bg-white px-3 py-1 text-sm font-medium">Try again</button>
        </div>
      )}
      {state.status === "ready" && (
        state.entries.length === 0 ? <p className="text-sm text-gray-700">No access recorded for these filters.</p> : (
          <>
            <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
              <table className="w-full text-sm">
                <caption className="sr-only">Data access entries, newest first</caption>
                <thead>
                  <tr className="border-b border-gray-200 text-left">
                    <th scope="col" className="px-3 py-2">When</th>
                    <th scope="col" className="px-3 py-2">Who</th>
                    <th scope="col" className="px-3 py-2">Resource</th>
                    <th scope="col" className="px-3 py-2">Purpose</th>
                  </tr>
                </thead>
                <tbody>
                  {state.entries.map((e) => (
                    <tr key={e.id} className="border-b border-gray-100">
                      <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(e.created_at)}</td>
                      <td className="px-3 py-2">{e.actor.display_name}</td>
                      <td className="px-3 py-2">{RESOURCE_LABELS[e.resource] ?? e.resource}</td>
                      <td className="px-3 py-2">{e.purpose ?? "Not recorded"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {state.nextBefore && (
              <button
                type="button"
                onClick={loadMore}
                disabled={state.loadingMore}
                className="min-h-6 rounded border border-gray-500 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 hover:bg-gray-50 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
              >
                {state.loadingMore ? "Loading older entries…" : "Load older entries"}
              </button>
            )}
          </>
        )
      )}
    </div>
  );
}

function FilterForm({ value, onApply }: { value: Filters; onApply: (f: Filters) => void }) {
  const [draft, setDraft] = useState(value);
  const resourceId = useId();
  const fromId = useId();
  const toId = useId();
  return (
    <form
      aria-label="Filter access log"
      className="flex flex-wrap items-end gap-3 rounded-xl border border-gray-200 bg-white p-3"
      onSubmit={(e) => { e.preventDefault(); onApply(draft); }}
    >
      <div>
        <label htmlFor={resourceId} className="block text-xs font-medium text-gray-700">Resource</label>
        <select id={resourceId} value={draft.resource} onChange={(e) => setDraft({ ...draft, resource: e.target.value as Filters["resource"] })}
          className="min-h-6 rounded border border-gray-400 px-2 py-1 text-sm">
          <option value="">All resources</option>
          {(Object.keys(RESOURCE_LABELS) as AccessLogResource[]).map((r) => <option key={r} value={r}>{RESOURCE_LABELS[r]}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor={fromId} className="block text-xs font-medium text-gray-700">From</label>
        <input id={fromId} type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          className="rounded border border-gray-400 px-2 py-1 text-sm" />
      </div>
      <div>
        <label htmlFor={toId} className="block text-xs font-medium text-gray-700">To (inclusive)</label>
        <input id={toId} type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          className="rounded border border-gray-400 px-2 py-1 text-sm" />
      </div>
      <button type="submit" className="min-h-6 rounded bg-[#1a1a1a] px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]">
        Apply
      </button>
    </form>
  );
}
