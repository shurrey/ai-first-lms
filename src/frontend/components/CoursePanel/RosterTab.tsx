"use client";

import { useState } from "react";
import { useSession } from "@/lib/session-context";
import { ApiError } from "@/lib/api";
import { useApiGet } from "@/lib/use-api";
import { AccessDenied } from "@/components/common/AccessDenied";
import { StudentDetail } from "./StudentDetail";

interface RosterStudent {
  id: string;
  name: string;
  session_count: number;
  last_active: string | null;
  total_turns: number;
}

/** The subset of AdvisorHome (GET /api/home) this tab reads. */
interface AdvisorHomeCaseload {
  role: "advisor";
  caseload: Array<{
    student_id: string;
    display_name: string;
    courses: Array<{ course: { course_id: string; title: string }; last_active?: string | null }>;
  }>;
}

interface StudentRef {
  id: string;
  name: string;
}

/** `advisees`: list the advisor's assigned students instead of a course roster. */
export function RosterTab({ advisees }: { advisees: boolean }) {
  const [selectedStudent, setSelectedStudent] = useState<StudentRef | null>(null);

  if (selectedStudent) {
    return <StudentDetail student={selectedStudent} onBack={() => setSelectedStudent(null)} />;
  }
  return advisees ? (
    <AdviseeRoster onSelectStudent={setSelectedStudent} />
  ) : (
    <CourseRoster onSelectStudent={setSelectedStudent} />
  );
}

function CourseRoster({ onSelectStudent }: { onSelectStudent: (s: StudentRef) => void }) {
  const { courseUuid } = useSession();
  const roster = useApiGet<{ students: RosterStudent[] }>(
    courseUuid && courseUuid !== "all" ? `/api/roster/${encodeURIComponent(courseUuid)}` : null
  );
  const students = roster.data?.students ?? [];

  if (roster.forbidden) return <AccessDenied what="This course's roster isn't available to you." />;
  if (roster.loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading roster...</p>;
  }
  if (roster.error) return <LoadError what="the roster" />;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Students ({students.length})
        </h3>
      </div>
      <div className="space-y-1">
        {students.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onSelectStudent(s)}
            className="flex w-full items-center justify-between rounded-lg border border-border bg-card p-2.5 text-left hover:bg-muted/50 transition-colors"
          >
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium truncate">{s.name}</div>
              <div className="text-[10px] text-muted-foreground">
                {s.session_count > 0
                  ? `${s.session_count} session${s.session_count !== 1 ? "s" : ""} \u00b7 ${s.total_turns} messages`
                  : "No sessions yet"}
              </div>
            </div>
            {s.session_count > 0 && <ActivityDot lastActive={s.last_active} />}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Advisor caseload from the server; never a client-side list of courses or students. */
function AdviseeRoster({ onSelectStudent }: { onSelectStudent: (s: StudentRef) => void }) {
  const home = useApiGet<AdvisorHomeCaseload>("/api/home");
  const caseload = [...(home.data?.caseload ?? [])].sort((a, b) =>
    a.display_name.localeCompare(b.display_name)
  );

  if (home.forbidden) return <AccessDenied />;
  if (home.loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading advisees...</p>;
  }
  if (home.error) {
    const notYet = home.error instanceof ApiError && home.error.status === 404;
    return notYet ? (
      <p className="text-xs text-muted-foreground">Your advisee list isn&apos;t available yet.</p>
    ) : (
      <LoadError what="your advisees" />
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Advisees ({caseload.length})
      </h3>
      <div className="space-y-1">
        {caseload.map((s) => (
          <button
            key={s.student_id}
            type="button"
            onClick={() => onSelectStudent({ id: s.student_id, name: s.display_name })}
            className="flex w-full items-center justify-between rounded-lg border border-border bg-card p-2.5 text-left hover:bg-muted/50 transition-colors"
          >
            <div className="text-xs font-medium truncate">{s.display_name}</div>
            <span className="text-[10px] text-muted-foreground shrink-0 ml-2">
              {s.courses.length} course{s.courses.length !== 1 ? "s" : ""}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function LoadError({ what }: { what: string }) {
  return (
    <p role="alert" className="text-xs text-destructive">
      Couldn&apos;t load {what}. Please try again.
    </p>
  );
}

function ActivityDot({ lastActive }: { lastActive: string | null }) {
  if (!lastActive) return null;
  const hoursAgo = (Date.now() - new Date(lastActive).getTime()) / 3600000;
  const color = hoursAgo < 1 ? "bg-green-500" : hoursAgo < 24 ? "bg-amber-400" : "bg-gray-300";
  return <span className={`inline-block h-2 w-2 rounded-full ${color} shrink-0`} />;
}
