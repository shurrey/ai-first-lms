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

interface ScoreDistribution {
  high: number;
  medium: number;
  low: number;
  at_risk: number;
  sampled: number;
}

interface StrugglingStudent {
  name: string;
  avg: number;
}

export function FacultyPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading course data...</p>;
  }

  const extra = (data.extra ?? {}) as {
    faculty_count?: number;
    score_distribution?: ScoreDistribution;
    struggling_students?: StrugglingStudent[];
    class_avg?: number;
  };

  const dist = extra.score_distribution;
  const struggling = extra.struggling_students ?? [];
  const classAvg = extra.class_avg ?? data.stats.avg_score;

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Class at a Glance</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          <StatRow label="Students" value={`${data.stats.submissions_count}`} />
          {extra.faculty_count !== undefined && (
            <StatRow label="Instructors" value={`${extra.faculty_count}`} />
          )}
          {data.current_module.total > 0 && (
            <StatRow label="Modules" value={`${data.current_module.total}`} />
          )}
          <StatRow label="Class Avg" value={`${Math.round(classAvg * 100)}%`} />
        </div>
      </section>

      {dist && (
        <section>
          <SectionLabel>Score Distribution</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex gap-1 mb-2 h-3">
              {dist.high > 0 && <div className="rounded-sm bg-green-500" style={{ flex: dist.high }} title={`High: ${dist.high}`} />}
              {dist.medium > 0 && <div className="rounded-sm bg-amber-400" style={{ flex: dist.medium }} title={`Medium: ${dist.medium}`} />}
              {dist.low > 0 && <div className="rounded-sm bg-orange-500" style={{ flex: dist.low }} title={`Low: ${dist.low}`} />}
              {dist.at_risk > 0 && <div className="rounded-sm bg-red-500" style={{ flex: dist.at_risk }} title={`At-risk: ${dist.at_risk}`} />}
            </div>
            <div className="flex justify-between text-[9px] text-muted-foreground">
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-green-500" />{dist.high} high</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-amber-400" />{dist.medium} mid</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-orange-500" />{dist.low} low</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-red-500" />{dist.at_risk} risk</span>
            </div>
            {dist.sampled < data.stats.submissions_count && (
              <p className="mt-1 text-[8px] text-muted-foreground">Based on sample of {dist.sampled} students</p>
            )}
          </div>
        </section>
      )}

      {struggling.length > 0 && (
        <section>
          <SectionLabel>Needs Attention</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {struggling.map((s, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{s.name}</span>
                <span className="shrink-0 font-mono text-destructive">{Math.round(s.avg * 100)}%</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("How is my class performing overall?")}>📊 Class performance</Pill>
          <Pill onClick={() => sendPrompt("Which students are at risk of falling behind?")}>⚠️ At-risk students</Pill>
          <Pill onClick={() => sendPrompt("Are there any submissions I need to grade?")}>📝 Grade submissions</Pill>
          <Pill onClick={() => sendPrompt("Help me create a quiz on the current module")}>🎯 Create quiz</Pill>
          <Pill onClick={() => sendPrompt("Draft an announcement for my class")}>📢 Announcement</Pill>
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
