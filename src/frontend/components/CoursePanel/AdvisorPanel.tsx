"use client";

import type { BriefCardPayload } from "@/lib/events";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

interface RiskSummary {
  at_risk: number;
  low: number;
  disengaged: number;
  on_track: number;
}

interface FlaggedStudent {
  name: string;
  avg: number;
}

export function AdvisorPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading...</p>;
  }

  const extra = (data.extra ?? {}) as {
    faculty?: string[];
    course_stats?: Array<{ course_id: string; name: string; students: number; avg_score: number }>;
    at_risk_students?: FlaggedStudent[];
    low_performing?: FlaggedStudent[];
    disengaged?: FlaggedStudent[];
    class_avg?: number;
    overall_avg?: number;
    is_cross_course?: boolean;
    risk_summary?: RiskSummary;
  };

  const risk = extra.risk_summary;
  const atRisk = extra.at_risk_students ?? [];
  const lowPerf = extra.low_performing ?? [];
  const disengaged = extra.disengaged ?? [];
  const classAvg = extra.class_avg ?? 0;

  return (
    <div className="space-y-4">
      {/* Caseload Overview */}
      <section>
        <SectionLabel>Caseload Overview</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          <StatRow label="Students" value={`${data.stats.submissions_count}`} />
          {extra.faculty && extra.faculty.length > 0 && (
            <StatRow label="Instructors" value={extra.faculty.join(", ")} />
          )}
          <StatRow label="Class Avg" value={`${Math.round(classAvg * 100)}%`} />
        </div>
      </section>

      {/* Course Health (cross-course view) */}
      {extra.course_stats && extra.course_stats.length > 1 && (
        <section>
          <SectionLabel>Course Health</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {extra.course_stats.map((cs, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{cs.name}</span>
                <span className="shrink-0 text-muted-foreground">
                  {cs.students}s · {Math.round(cs.avg_score * 100)}%
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Risk Overview */}
      {risk && (
        <section>
          <SectionLabel>Student Risk</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex gap-1 mb-2 h-3">
              {risk.on_track > 0 && <div className="rounded-sm bg-green-500" style={{ flex: risk.on_track }} />}
              {risk.low > 0 && <div className="rounded-sm bg-amber-400" style={{ flex: risk.low }} />}
              {risk.at_risk > 0 && <div className="rounded-sm bg-red-500" style={{ flex: risk.at_risk }} />}
              {risk.disengaged > 0 && <div className="rounded-sm bg-gray-400" style={{ flex: risk.disengaged }} />}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[9px] text-muted-foreground">
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-green-500" />{risk.on_track} on track</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-amber-400" />{risk.low} low</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-red-500" />{risk.at_risk} at-risk</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-gray-400" />{risk.disengaged} disengaged</span>
            </div>
          </div>
        </section>
      )}

      {/* At-Risk Students */}
      {atRisk.length > 0 && (
        <section>
          <SectionLabel>At-Risk Students</SectionLabel>
          <div className="rounded-lg border border-red-200 bg-red-50/50 dark:border-red-900 dark:bg-red-950/20 p-3 space-y-1">
            {atRisk.map((s, i) => (
              <button
                key={i}
                onClick={() => sendPrompt(`Tell me about ${s.name}'s situation. Why are they at risk?`)}
                className="flex w-full items-center justify-between text-xs hover:bg-red-100 dark:hover:bg-red-900/30 rounded px-1 py-0.5 -mx-1 transition-colors text-left"
              >
                <span className="truncate pr-2">{s.name}</span>
                <span className="shrink-0 font-mono text-destructive">{Math.round(s.avg * 100)}%</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Low Performing */}
      {lowPerf.length > 0 && (
        <section>
          <SectionLabel>Needs Support</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {lowPerf.map((s, i) => (
              <button
                key={i}
                onClick={() => sendPrompt(`Tell me about ${s.name}'s performance and how I can support them.`)}
                className="flex w-full items-center justify-between text-xs hover:bg-muted rounded px-1 py-0.5 -mx-1 transition-colors text-left"
              >
                <span className="truncate pr-2">{s.name}</span>
                <span className="shrink-0 font-mono text-amber-600">{Math.round(s.avg * 100)}%</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Quick Actions */}
      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("Which students need attention in this course?")}>⚠️ At-risk students</Pill>
          <Pill onClick={() => sendPrompt("Show me engagement trends for this course")}>📈 Engagement trends</Pill>
          <Pill onClick={() => sendPrompt("Which students are behind on degree requirements?")}>🎓 Degree progress</Pill>
          <Pill onClick={() => sendPrompt("Help me plan outreach for struggling students")}>📧 Plan outreach</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
