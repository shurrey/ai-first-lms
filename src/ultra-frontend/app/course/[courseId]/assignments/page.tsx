"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, FileText } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { FEEDBACK_STATUS_TEXT, formatDateTime, showsAssignmentsTab } from "@/lib/assessment";
import { NoAccess } from "@/components/NoAccess";
import type { Page, Submission } from "@/lib/types";

type Load = { status: "loading" } | { status: "ready"; items: Submission[] } | { status: "error"; message: string };

export default function AssignmentsPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { activeRole, capabilities } = useAuth();
  if (!showsAssignmentsTab(activeRole, capabilities)) return <NoAccess />;
  return <AssignmentList courseId={courseId} />;
}

function AssignmentList({ courseId }: { courseId: string }) {
  const [state, setState] = useState<Load>({ status: "loading" });

  const load = useCallback(() => {
    setState({ status: "loading" });
    apiJson<Page<Submission>>(`/api/submissions?course_id=${encodeURIComponent(courseId)}`)
      .then((page) => setState({ status: "ready", items: page.items }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return;
        setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
  }, [courseId]);
  useEffect(load, [load]);

  return (
    <div className="max-w-3xl space-y-4 p-6">
      <div>
        <h2 className="text-lg font-semibold">Your assignments</h2>
        <p className="text-sm text-gray-700">Submit drafts for criterion feedback, revise, then submit your final version.</p>
      </div>
      {state.status === "loading" && <p role="status" className="text-sm text-gray-700">Loading your submissions…</p>}
      {state.status === "error" && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <p>Couldn&apos;t load your submissions: {state.message}</p>
          <button type="button" onClick={load} className="mt-2 min-h-6 rounded border border-red-300 bg-white px-3 py-1 text-sm font-medium">Try again</button>
        </div>
      )}
      {state.status === "ready" && (state.items.length === 0 ? (
        <p className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-gray-700">
          You haven&apos;t submitted anything in this course yet. Open an assignment from your planner or calendar to submit a draft.
        </p>
      ) : (
        <ul className="space-y-2">
          {state.items.map((s) => (
            <li key={s.id}>
              <Link
                href={`/course/${courseId}/assignments/${s.assignment_id}`}
                className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
              >
                <FileText aria-hidden="true" className="h-5 w-5 shrink-0 text-gray-600" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-gray-900">{s.assignment_title ?? "Assignment"}</span>
                  <span className="block text-xs text-gray-700">
                    Version {s.version} ({s.status}) · {formatDateTime(s.submitted_at)}
                    {s.feedback_status ? ` · ${FEEDBACK_STATUS_TEXT[s.feedback_status]}` : ""}
                  </span>
                </span>
                <ChevronRight aria-hidden="true" className="h-4 w-4 text-gray-500" />
              </Link>
            </li>
          ))}
        </ul>
      ))}
    </div>
  );
}
