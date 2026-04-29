"use client";

import { useEffect, useState, useRef } from "react";
import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import { API_BASE } from "@/lib/api";
import type { BriefCardPayload } from "@/lib/events";
import { MasteryPanel } from "./MasteryPanel";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLTextAreaElement>("form textarea");
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

export function StudentPanel({ data }: { data: BriefCardPayload | null }) {
  const { personId, courseUuid } = useSession();
  const { status } = useTurn();
  const [liveMastery, setLiveMastery] = useState<any>(null);
  const prevStatusRef = useRef(status);

  // Seed from brief data
  const briefMastery = (data?.extra as any)?.mastery_data;

  // Refetch mastery data when a turn completes
  useEffect(() => {
    if (prevStatusRef.current === "streaming" && status === "done" && personId && courseUuid && courseUuid !== "all") {
      fetch(`${API_BASE}/api/mastery/${personId}/${courseUuid}`)
        .then((r) => r.json())
        .then((d) => {
          if (d.summary) setLiveMastery(d);
        })
        .catch(() => {});
    }
    prevStatusRef.current = status;
  }, [status, personId, courseUuid]);

  // Use live data if available, fall back to brief data
  const masteryData = liveMastery || briefMastery;

  if (data && masteryData?.summary) {
    return <MasteryPanel data={masteryData} />;
  }

  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading course data...</p>;
  }

  const progressPct = data.current_module.total > 0
    ? Math.round((data.current_module.index / data.current_module.total) * 100)
    : 0;

  return (
    <div className="space-y-4">
      {data.current_module.total > 0 && (
        <section>
          <SectionLabel>Course Progress</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="mb-1 flex justify-between text-xs text-muted-foreground">
              <span>Module {data.current_module.index} of {data.current_module.total}</span>
              <span>{data.current_module.title}</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted">
              <div className="h-1.5 rounded-full bg-primary transition-all" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        </section>
      )}

      {data.stats.total_assignments > 0 && (
        <section>
          <SectionLabel>Your Performance</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            <StatRow label="Avg Score" value={`${Math.round(data.stats.avg_score * 100)}%`} />
            <StatRow label="Submitted" value={`${data.stats.submissions_count}/${data.stats.total_assignments}`} />
            {data.assignments.length > 0 && (() => {
              const focus = data.assignments.reduce((a, b) =>
                (a.score ?? 1) < (b.score ?? 1) ? a : b
              );
              return focus.score !== null ? (
                <StatRow label="Focus Area" value={focus.title} valueClass="text-amber-600 dark:text-amber-400" />
              ) : null;
            })()}
          </div>
        </section>
      )}

      {data.assignments.length > 0 && (
        <section>
          <SectionLabel>Assignments</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {data.assignments.map((a, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{a.title}</span>
                <span className={`shrink-0 font-mono ${
                  a.score !== null && a.score < 0.5 ? "text-destructive"
                    : a.score !== null ? "text-green-600 dark:text-green-400"
                    : "text-muted-foreground"
                }`}>
                  {a.score !== null ? `${Math.round(a.score * 100)}%` : "--"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("What assignments do I have?")}>📋 My assignments</Pill>
          <Pill onClick={() => sendPrompt("What are my areas to focus on?")}>🎯 Growth areas</Pill>
          <Pill onClick={() => sendPrompt("Quiz me on the current module")}>📝 Quiz me</Pill>
          <Pill onClick={() => sendPrompt("Help me build a study plan")}>📚 Study plan</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function StatRow({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={valueClass ?? "font-medium"}>{value}</span>
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
