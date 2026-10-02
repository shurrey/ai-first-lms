"use client";

import { useState } from "react";
import { useSession } from "@/lib/session-context";
import { useAuth } from "@/lib/auth-context";
import { useApiGet } from "@/lib/use-api";
import { AccessDenied } from "@/components/common/AccessDenied";
import { TranscriptView } from "./TranscriptView";

interface StudentInfo {
  id: string;
  name: string;
}

interface SessionEntry {
  session_id: string;
  course_id: string | null;
  course_title: string;
  created_at: string;
  turn_count: number;
  first_message: string;
}

interface CourseEntry {
  course_id: string;
  title: string;
  mastery: number;
  total_concepts: number;
  microcredentials_earned: number;
  microcredentials_total: number;
  session_count: number;
  last_active: string | null;
}

export function StudentDetail({
  student,
  onBack,
}: {
  student: StudentInfo;
  onBack: () => void;
}) {
  const { courseUuid } = useSession();
  const { me } = useAuth();

  // Advisor sees cross-course view; faculty sees session list for current course
  if (me.active_role === "advisor" || courseUuid === "all") {
    return <AdvisorStudentView student={student} onBack={onBack} />;
  }

  return <FacultyStudentView student={student} courseId={courseUuid!} onBack={onBack} />;
}

/** Faculty view: session list for a student in the current course */
function FacultyStudentView({
  student,
  courseId,
  onBack,
}: {
  student: StudentInfo;
  courseId: string;
  onBack: () => void;
}) {
  const sessionsQ = useApiGet<{ sessions: SessionEntry[] }>(
    `/api/student/${encodeURIComponent(student.id)}/sessions?course_id=${encodeURIComponent(courseId)}`
  );
  const sessions = sessionsQ.data?.sessions ?? [];
  const { loading, forbidden } = sessionsQ;
  const [selectedSession, setSelectedSession] = useState<string | null>(null);


  if (selectedSession) {
    return (
      <TranscriptView
        sessionId={selectedSession}
        onBack={() => setSelectedSession(null)}
      />
    );
  }

  return (
    <div className="space-y-3">
      <button
        onClick={onBack}
        className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      >
        &larr; Back to roster
      </button>

      <div className="rounded-lg border border-border bg-card p-3">
        <div className="text-sm font-medium">{student.name}</div>
        <div className="text-[10px] text-muted-foreground mt-0.5">
          {sessions.length} tutoring session{sessions.length !== 1 ? "s" : ""}
        </div>
      </div>

      {forbidden ? (
        <AccessDenied />
      ) : loading ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading sessions...</p>
      ) : sessions.length === 0 ? (
        <p className="text-xs text-muted-foreground">No tutoring sessions yet.</p>
      ) : (
        <div className="space-y-1.5">
          <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Sessions
          </h3>
          {sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => setSelectedSession(s.session_id)}
              className="w-full rounded-lg border border-border bg-card p-2.5 text-left hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">
                  {formatDate(s.created_at)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {s.turn_count} messages
                </span>
              </div>
              {s.first_message && (
                <div className="text-xs mt-1 truncate text-foreground/80">
                  &ldquo;{s.first_message}&rdquo;
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Advisor view: cross-course overview for a student */
function AdvisorStudentView({
  student,
  onBack,
}: {
  student: StudentInfo;
  onBack: () => void;
}) {
  const coursesQ = useApiGet<{ courses: CourseEntry[] }>(
    `/api/student/${encodeURIComponent(student.id)}/courses`
  );
  const courses = coursesQ.data?.courses ?? [];
  const { loading, forbidden } = coursesQ;
  const [selectedCourse, setSelectedCourse] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);


  // Transcript view
  if (selectedSession) {
    return (
      <TranscriptView
        sessionId={selectedSession}
        onBack={() => setSelectedSession(null)}
      />
    );
  }

  // Session list for a specific course
  if (selectedCourse) {
    return (
      <CourseSessionList
        student={student}
        courseId={selectedCourse}
        onBack={() => setSelectedCourse(null)}
        onSelectSession={setSelectedSession}
      />
    );
  }

  return (
    <div className="space-y-3">
      <button
        onClick={onBack}
        className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      >
        &larr; Back to advisees
      </button>

      <div className="rounded-lg border border-border bg-card p-3">
        <div className="text-sm font-medium">{student.name}</div>
        <div className="text-[10px] text-muted-foreground mt-0.5">
          Enrolled in {courses.length} course{courses.length !== 1 ? "s" : ""}
        </div>
      </div>

      {forbidden ? (
        <AccessDenied />
      ) : loading ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading courses...</p>
      ) : (
        <div className="space-y-2">
          {courses.map((c) => {
            const pct = c.total_concepts > 0
              ? Math.round((c.mastery / c.total_concepts) * 100)
              : 0;
            return (
              <button
                key={c.course_id}
                onClick={() => setSelectedCourse(c.course_id)}
                className="w-full rounded-lg border border-border bg-card p-3 text-left hover:bg-muted/50 transition-colors"
              >
                <div className="text-xs font-medium">{c.title}</div>
                <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  {pct > 0 && (
                    <div className="bg-green-500 rounded-full" style={{ width: `${pct}%` }} />
                  )}
                </div>
                <div className="mt-1 flex justify-between text-[9px] text-muted-foreground">
                  <span>
                    {c.mastery}/{c.total_concepts} mastered
                    {" \u00b7 "}
                    {c.microcredentials_earned}/{c.microcredentials_total} credentials
                  </span>
                  <span>{c.session_count} sessions</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Session list for a student in a specific course (used from advisor drill-down) */
function CourseSessionList({
  student,
  courseId,
  onBack,
  onSelectSession,
}: {
  student: StudentInfo;
  courseId: string;
  onBack: () => void;
  onSelectSession: (sessionId: string) => void;
}) {
  const sessionsQ = useApiGet<{ sessions: SessionEntry[] }>(
    `/api/student/${encodeURIComponent(student.id)}/sessions?course_id=${encodeURIComponent(courseId)}`
  );
  const sessions = sessionsQ.data?.sessions ?? [];
  const { loading, forbidden } = sessionsQ;


  return (
    <div className="space-y-3">
      <button
        onClick={onBack}
        className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      >
        &larr; Back to courses
      </button>

      <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {student.name} &mdash; Sessions
      </h3>

      {forbidden ? (
        <AccessDenied />
      ) : loading ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading sessions...</p>
      ) : sessions.length === 0 ? (
        <p className="text-xs text-muted-foreground">No sessions in this course.</p>
      ) : (
        <div className="space-y-1.5">
          {sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => onSelectSession(s.session_id)}
              className="w-full rounded-lg border border-border bg-card p-2.5 text-left hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">
                  {formatDate(s.created_at)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {s.turn_count} messages
                </span>
              </div>
              {s.first_message && (
                <div className="text-xs mt-1 truncate text-foreground/80">
                  &ldquo;{s.first_message}&rdquo;
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
