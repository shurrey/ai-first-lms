"use client";

import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import { StudentPanel } from "./StudentPanel";
import { FacultyPanel } from "./FacultyPanel";
import { AdvisorPanel } from "./AdvisorPanel";
import { AdminPanel } from "./AdminPanel";

export function CoursePanel() {
  const { persona, sessionId } = useSession();
  const { briefCardData } = useTurn();

  if (!sessionId) {
    return (
      <aside className="flex h-full flex-col items-center justify-center border-l border-border bg-muted/30 p-4">
        <p className="text-xs text-muted-foreground">Select a course to get started.</p>
      </aside>
    );
  }

  return (
    <aside className="flex h-full flex-col overflow-y-auto border-l border-border bg-muted/30 p-4">
      {persona === "student" && <StudentPanel data={briefCardData} />}
      {persona === "faculty" && <FacultyPanel data={briefCardData} />}
      {persona === "advisor" && <AdvisorPanel data={briefCardData} />}
      {persona === "admin" && <AdminPanel data={briefCardData} />}
    </aside>
  );
}
