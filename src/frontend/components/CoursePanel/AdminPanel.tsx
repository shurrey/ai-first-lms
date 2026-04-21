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

interface RosterBreakdown {
  students: number;
  faculty: number;
  advisors: number;
  total: number;
}

export function AdminPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading...</p>;
  }

  const extra = (data.extra ?? {}) as {
    faculty?: string[];
    faculty_details?: Array<{ name: string; id: string }>;
    advisor_count?: number;
    total_evidence?: number;
    avg_score?: number;
    roster_breakdown?: RosterBreakdown;
    modules?: number;
  };

  const breakdown = extra.roster_breakdown;
  const faculty = extra.faculty_details ?? [];
  const avgScore = extra.avg_score ?? 0;

  return (
    <div className="space-y-4">
      {/* Course Overview */}
      <section>
        <SectionLabel>Course Overview</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          {breakdown && (
            <>
              <StatRow label="Total Roster" value={`${breakdown.total}`} />
              <StatRow label="Students" value={`${breakdown.students}`} />
              <StatRow label="Faculty" value={`${breakdown.faculty}`} />
              <StatRow label="Advisors" value={`${breakdown.advisors}`} />
            </>
          )}
          {extra.modules !== undefined && extra.modules > 0 && (
            <StatRow label="Modules" value={`${extra.modules}`} />
          )}
          <StatRow label="Class Avg" value={`${Math.round(avgScore * 100)}%`} />
          {extra.total_evidence !== undefined && (
            <StatRow label="Evidence Records" value={`${extra.total_evidence}`} />
          )}
        </div>
      </section>

      {/* Faculty */}
      {faculty.length > 0 && (
        <section>
          <SectionLabel>Faculty</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {faculty.map((f, i) => (
              <button
                key={i}
                onClick={() => sendPrompt(`How is ${f.name} performing as an instructor? What's their grading status?`)}
                className="flex w-full items-center text-xs hover:bg-muted rounded px-1 py-0.5 -mx-1 transition-colors text-left"
              >
                <span>{f.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Quick Actions */}
      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("Give me an overview of this course's health")}>🏥 Course health</Pill>
          <Pill onClick={() => sendPrompt("What are the enrollment numbers?")}>📊 Enrollment stats</Pill>
          <Pill onClick={() => sendPrompt("What's the status of the grading pipeline?")}>📝 Grading pipeline</Pill>
          <Pill onClick={() => sendPrompt("How are the instructors performing?")}>👩‍🏫 Faculty review</Pill>
          <Pill onClick={() => sendPrompt("Are there any accessibility concerns?")}>♿ Accessibility</Pill>
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
