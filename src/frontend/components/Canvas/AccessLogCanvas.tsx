"use client";

import { useId, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ACCESS_LOG_RESOURCES, toAccessLogRow } from "@/lib/assessment";

interface AccessLogPage {
  entries: Record<string, unknown>[];
  next_before?: string | null;
}

function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Start of the given local day as ISO 8601; `addDays` 1 gives the exclusive end of that day. */
function dayBoundary(date: string, addDays = 0): string {
  const d = new Date(`${date}T00:00:00`);
  d.setDate(d.getDate() + addDays);
  return d.toISOString();
}

/**
 * Admin view of who read a learner's transcript, profile, analyst summaries or
 * submissions (spec §12.3), from GET /api/access-log.
 */
export function AccessLogCanvas({ subjectId, subjectName }: { subjectId: string; subjectName: string }) {
  const { me } = useAuth();
  const isAdmin = me.active_role === "admin";
  const [resource, setResource] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const headingId = useId();
  const resourceId = useId();
  const fromId = useId();
  const toId = useId();

  const params = new URLSearchParams({ subject_id: subjectId });
  if (resource) params.set("resource", resource);
  if (from) params.set("from", dayBoundary(from));
  if (to) params.set("to", dayBoundary(to, 1));
  const base = `/api/access-log?${params.toString()}`;

  const query = useInfiniteQuery({
    queryKey: ["api", base],
    queryFn: ({ pageParam }) =>
      apiJson<AccessLogPage>(pageParam ? `${base}&before=${encodeURIComponent(pageParam)}` : base),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before ?? null,
    enabled: isAdmin,
    retry: false,
  });

  if (!isAdmin) return null;

  const rows = (query.data?.pages ?? []).flatMap((p) => p.entries ?? []).map(toAccessLogRow);
  const field = "rounded-md border border-input bg-background px-2 py-1 min-h-6";

  let table: React.ReactNode;
  if (query.isPending) table = <p role="status">Loading access log…</p>;
  else if (query.isError) {
    table = (
      <p role="alert">
        {query.error instanceof ApiError && query.error.status === 403
          ? "Only admins can view the access log."
          : "Couldn't load the access log. Please try again."}
      </p>
    );
  } else {
    table = (
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Access log entries">
        <table className="w-full border-collapse text-xs">
          <caption className="sr-only">Reads of {subjectName}&apos;s data, newest first</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="px-2 py-1 text-left font-medium">When</th>
              <th scope="col" className="px-2 py-1 text-left font-medium">Who</th>
              <th scope="col" className="px-2 py-1 text-left font-medium">What</th>
              <th scope="col" className="px-2 py-1 text-left font-medium">Purpose</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-2 py-2 text-muted-foreground">
                  No one else has read this learner&apos;s data for these filters.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-b border-border/50">
                  <td className="px-2 py-1 whitespace-nowrap">
                    {r.created_at ? new Date(r.created_at).toLocaleString() : "–"}
                  </td>
                  <td className="px-2 py-1">
                    {r.actor_name}
                    {r.actor_role && <span className="text-muted-foreground"> ({humanize(r.actor_role)})</span>}
                  </td>
                  <td className="px-2 py-1">{humanize(r.resource)}</td>
                  <td className="px-2 py-1">{r.purpose ?? "–"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <section aria-labelledby={headingId} className="space-y-2 text-sm" data-testid="access-log-canvas">
      <h3 id={headingId} className="text-sm font-semibold">
        Data access log
      </h3>
      <p className="text-xs text-muted-foreground">
        Who read {subjectName}&apos;s transcripts, profile, analyst summaries or submissions.
      </p>
      <div role="group" aria-label="Filter access log" className="flex flex-wrap items-end gap-2 text-xs">
        <div className="flex flex-col">
          <label htmlFor={resourceId} className="font-medium">Resource</label>
          <select id={resourceId} value={resource} onChange={(e) => setResource(e.target.value)} className={field}>
            <option value="">All</option>
            {ACCESS_LOG_RESOURCES.map((r) => (
              <option key={r} value={r}>{humanize(r)}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col">
          <label htmlFor={fromId} className="font-medium">From</label>
          <input id={fromId} type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={field} />
        </div>
        <div className="flex flex-col">
          <label htmlFor={toId} className="font-medium">To</label>
          <input id={toId} type="date" value={to} onChange={(e) => setTo(e.target.value)} className={field} />
        </div>
      </div>
      {table}
      {query.hasNextPage && (
        <button
          type="button"
          onClick={() => query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          className="min-h-6 rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-60"
        >
          {query.isFetchingNextPage ? "Loading…" : "Load older entries"}
        </button>
      )}
    </section>
  );
}
