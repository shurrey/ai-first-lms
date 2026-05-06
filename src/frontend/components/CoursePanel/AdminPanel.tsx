"use client";

import type { BriefCardPayload } from "@/lib/events";
import { sendPrompt, SectionLabel, Pill, StatRow } from "./shared";

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
    faculty_details?: Array<{ name: string; id: string; courses?: string[] }>;
    course_details?: Array<{ course_id: string; name: string; students: number; faculty: string[]; modules: number; avg_score: number }>;
    advisor_count?: number;
    total_evidence?: number;
    avg_score?: number;
    is_cross_course?: boolean;
    roster_breakdown?: RosterBreakdown & { courses?: number };
    modules?: number;
  };

  const breakdown = extra.roster_breakdown;
  const faculty = extra.faculty_details ?? [];
  const courseDetails = extra.course_details ?? [];
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

      {/* Course Health Table (cross-course) */}
      {courseDetails.length > 1 && (
        <section>
          <SectionLabel>Course Health</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1.5">
            {courseDetails.map((cd, i) => (
              <div key={i} className="text-xs">
                <div className="flex justify-between font-medium">
                  <span>{cd.name}</span>
                  <span>{Math.round(cd.avg_score * 100)}%</span>
                </div>
                <div className="text-[9px] text-muted-foreground">
                  {cd.students} students · {cd.modules} modules · {cd.faculty.join(", ")}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

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

