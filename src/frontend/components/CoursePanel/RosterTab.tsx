"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/lib/session-context";
import { API_BASE } from "@/lib/api";
import { StudentDetail } from "./StudentDetail";

interface RosterStudent {
  id: string;
  name: string;
  session_count: number;
  last_active: string | null;
  total_turns: number;
}

export function RosterTab() {
  const { persona, courseUuid } = useSession();
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedStudent, setSelectedStudent] = useState<RosterStudent | null>(null);

  useEffect(() => {
    if (!courseUuid || courseUuid === "all") {
      setLoading(false);
      return;
    }
    setLoading(true);
    setSelectedStudent(null);
    fetch(`${API_BASE}/api/roster/${courseUuid}`)
      .then((r) => r.json())
      .then((data) => {
        setStudents(data.students || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [courseUuid]);

  // Drill-down into a student
  if (selectedStudent) {
    return (
      <StudentDetail
        student={selectedStudent}
        onBack={() => setSelectedStudent(null)}
      />
    );
  }

  if (loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading roster...</p>;
  }

  if (courseUuid === "all") {
    return <AdviseeRoster onSelectStudent={setSelectedStudent} />;
  }

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
            onClick={() => setSelectedStudent(s)}
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
            {s.session_count > 0 && (
              <ActivityDot lastActive={s.last_active} />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Advisor view: flat list of all advisees across courses */
function AdviseeRoster({ onSelectStudent }: { onSelectStudent: (s: RosterStudent) => void }) {
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch roster from all courses and deduplicate
    const courseIds = [
      "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
      "23b8c1e9-3924-46de-beb1-3b9046685257",
      "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9",
      "972a8469-1641-4f82-8b9d-2434e465e150",
    ];

    Promise.all(
      courseIds.map((cid) =>
        fetch(`${API_BASE}/api/roster/${cid}`)
          .then((r) => r.json())
          .then((d) => d.students || [])
      )
    ).then((results) => {
      const seen = new Set<string>();
      const deduped: RosterStudent[] = [];
      for (const roster of results) {
        for (const s of roster) {
          if (!seen.has(s.id)) {
            seen.add(s.id);
            deduped.push(s);
          }
        }
      }
      deduped.sort((a, b) => a.name.localeCompare(b.name));
      setStudents(deduped);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading advisees...</p>;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Advisees ({students.length})
      </h3>
      <div className="space-y-1">
        {students.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelectStudent(s)}
            className="flex w-full items-center justify-between rounded-lg border border-border bg-card p-2.5 text-left hover:bg-muted/50 transition-colors"
          >
            <div className="text-xs font-medium truncate">{s.name}</div>
            <span className="text-[10px] text-muted-foreground shrink-0 ml-2">
              {s.session_count > 0 ? `${s.session_count} sessions` : ""}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ActivityDot({ lastActive }: { lastActive: string | null }) {
  if (!lastActive) return null;
  const hoursAgo = (Date.now() - new Date(lastActive).getTime()) / 3600000;
  const color = hoursAgo < 1 ? "bg-green-500" : hoursAgo < 24 ? "bg-amber-400" : "bg-gray-300";
  return <span className={`inline-block h-2 w-2 rounded-full ${color} shrink-0`} />;
}
