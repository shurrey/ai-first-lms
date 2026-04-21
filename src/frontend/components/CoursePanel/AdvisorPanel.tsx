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

export function AdvisorPanel({ data }: { data: BriefCardPayload | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Caseload Overview</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-1">
          <StatRow label="Students" value={`${data.stats.submissions_count}`} />
        </div>
      </section>

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("Which students need attention in this course?")}>⚠️ At-risk students</Pill>
          <Pill onClick={() => sendPrompt("Show me engagement trends for this course")}>📈 Engagement trends</Pill>
          <Pill onClick={() => sendPrompt("Which students are behind on degree requirements?")}>🎓 Degree progress</Pill>
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
