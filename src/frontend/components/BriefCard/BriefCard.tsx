"use client";

import type { BriefCardPayload } from "@/lib/events";

interface BriefCardProps {
  data: BriefCardPayload;
}

export function BriefCard({ data }: BriefCardProps) {
  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      {/* Header */}
      <div>
        <p className="text-sm font-semibold">{data.student_name}</p>
        {data.course_title && (
          <p className="text-xs text-muted-foreground">{data.course_title}</p>
        )}
      </div>

      {/* Persona-specific content */}
      {data.persona === "student" && <StudentCardBody data={data} />}
      {data.persona === "faculty" && <FacultyCardBody data={data} />}
      {data.persona === "advisor" && <AdvisorCardBody data={data} />}
      {data.persona === "admin" && <AdminCardBody data={data} />}

      {/* Suggested Actions — shared across all personas */}
      {data.suggested_actions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.suggested_actions.map((action, i) => (
            <button
              key={i}
              onClick={() => {
                console.log("[BriefCard] Pill clicked:", action.prompt);
                const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
                const form = input?.closest("form");
                if (input && form) {
                  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
                  nativeSetter?.call(input, action.prompt);
                  // React 16+ listens for 'input' events via its synthetic system
                  input.dispatchEvent(new Event("input", { bubbles: true }));
                  // Also dispatch 'change' for good measure
                  input.dispatchEvent(new Event("change", { bubbles: true }));
                  // Wait for React to process, then submit
                  requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                      form.requestSubmit();
                    });
                  });
                }
              }}
              className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors"
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function StudentCardBody({ data }: { data: BriefCardPayload }) {
  const progressPct = data.current_module.total > 0
    ? Math.round((data.current_module.index / data.current_module.total) * 100)
    : 0;

  return (
    <>
      {/* Module Progress */}
      {data.current_module.total > 0 && (
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted-foreground">
            <span>Module {data.current_module.index} of {data.current_module.total}</span>
            <span>{data.current_module.title}</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted">
            <div
              className="h-1.5 rounded-full bg-primary transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Assignments */}
      {data.assignments.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Assignments
          </p>
          <div className="space-y-1">
            {data.assignments.map((a, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{a.title}</span>
                <span className={`shrink-0 font-mono ${
                  a.score !== null && a.score < 0.5
                    ? "text-destructive"
                    : a.score !== null
                    ? "text-green-600 dark:text-green-400"
                    : "text-muted-foreground"
                }`}>
                  {a.score !== null ? `${Math.round(a.score * 100)}%` : "--"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stats */}
      {data.stats.total_assignments > 0 && (
        <div className="flex gap-3 text-xs text-muted-foreground">
          <span>Avg: {Math.round(data.stats.avg_score * 100)}%</span>
          <span>{data.stats.submissions_count}/{data.stats.total_assignments} submitted</span>
        </div>
      )}
    </>
  );
}

function FacultyCardBody({ data }: { data: BriefCardPayload }) {
  return (
    <>
      {/* Course modules */}
      {data.current_module.total > 0 && (
        <div className="text-xs text-muted-foreground">
          {data.current_module.total} modules in course
        </div>
      )}

      {/* Class stats */}
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Class Overview
        </p>
        <div className="flex gap-3 text-xs text-muted-foreground">
          <span>{data.stats.submissions_count} students enrolled</span>
        </div>
      </div>
    </>
  );
}

function AdvisorCardBody({ data }: { data: BriefCardPayload }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Advising Overview
      </p>
      <div className="text-xs text-muted-foreground">
        {data.stats.submissions_count > 0
          ? `${data.stats.submissions_count} students in this course`
          : "No enrollment data available"}
      </div>
    </div>
  );
}

function AdminCardBody({ data }: { data: BriefCardPayload }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Administration
      </p>
      <div className="text-xs text-muted-foreground">
        {data.stats.submissions_count > 0
          ? `${data.stats.submissions_count} students enrolled`
          : "No enrollment data available"}
      </div>
    </div>
  );
}
