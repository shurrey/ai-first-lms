"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/lib/session-context";
import { API_BASE } from "@/lib/api";
import type { BriefCardPayload } from "@/lib/events";
import { sendPrompt, SectionLabel, Pill, StatRow } from "./shared";

interface PendingCredential {
  id: string;
  person_id: string;
  student_name: string;
  microcredential_id: string;
  credential_title: string;
  created_at: string;
}

interface ScoreDistribution {
  high: number;
  medium: number;
  low: number;
  at_risk: number;
}

interface StrugglingStudent {
  name: string;
  avg: number;
}

export function FacultyPanel({ data }: { data: BriefCardPayload | null }) {
  const { courseUuid, personId } = useSession();
  const [pendingCreds, setPendingCreds] = useState<PendingCredential[]>([]);
  const [approving, setApproving] = useState<string | null>(null);

  useEffect(() => {
    if (!courseUuid || courseUuid === "all") return;
    fetch(`${API_BASE}/api/pending-credentials/${courseUuid}`)
      .then((r) => r.json())
      .then((d) => setPendingCreds(d.pending || []))
      .catch(() => {});
  }, [courseUuid]);

  const handleApprove = async (pendingId: string) => {
    if (!personId) return;
    setApproving(pendingId);
    try {
      await fetch(`${API_BASE}/api/approve-credential/${pendingId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer_id: personId }),
      });
      setPendingCreds((prev) => prev.filter((c) => c.id !== pendingId));
    } catch {
      // ignore
    } finally {
      setApproving(null);
    }
  };

  const handleBulkApprove = async () => {
    if (!personId || pendingCreds.length === 0) return;
    setApproving("bulk");
    try {
      await fetch(`${API_BASE}/api/approve-credentials/bulk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pending_ids: pendingCreds.map((c) => c.id),
          reviewer_id: personId,
        }),
      });
      setPendingCreds([]);
    } catch {
      // ignore
    } finally {
      setApproving(null);
    }
  };

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
          </div>
        </section>
      )}

      {pendingCreds.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-1.5">
            <SectionLabel>Pending Badges ({pendingCreds.length})</SectionLabel>
            {pendingCreds.length > 1 && (
              <button
                onClick={handleBulkApprove}
                disabled={approving === "bulk"}
                className="text-[10px] text-primary hover:underline disabled:opacity-50"
              >
                {approving === "bulk" ? "Approving..." : "Approve all"}
              </button>
            )}
          </div>
          <div className="space-y-1.5">
            {pendingCreds.map((c) => (
              <div key={c.id} className="rounded-lg border border-amber-200 bg-amber-50/50 dark:border-amber-900 dark:bg-amber-950/20 p-2.5">
                <div className="flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium truncate">{c.student_name}</div>
                    <div className="text-[10px] text-muted-foreground">{c.credential_title}</div>
                  </div>
                  <div className="flex gap-1 shrink-0 ml-2">
                    <button
                      onClick={() => sendPrompt(`Show me the evidence for ${c.student_name}'s ${c.credential_title} credential`)}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] hover:bg-muted"
                    >
                      Review
                    </button>
                    <button
                      onClick={() => handleApprove(c.id)}
                      disabled={approving === c.id}
                      className="rounded border border-green-300 bg-green-50 px-1.5 py-0.5 text-[10px] text-green-700 hover:bg-green-100 dark:border-green-800 dark:bg-green-950 dark:text-green-400 disabled:opacity-50"
                    >
                      {approving === c.id ? "..." : "Approve"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {struggling.length > 0 && (
        <section>
          <SectionLabel>Needs Attention</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1">
            {struggling.map((s, i) => (
              <button
                key={i}
                onClick={() => sendPrompt(`Tell me about ${s.name}'s performance. Why do they need attention?`)}
                className="flex w-full items-center justify-between text-xs hover:bg-muted rounded px-1 py-0.5 -mx-1 transition-colors text-left"
              >
                <span className="truncate pr-2">{s.name}</span>
                <span className="shrink-0 font-mono text-destructive">{Math.round(s.avg * 100)}%</span>
              </button>
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

