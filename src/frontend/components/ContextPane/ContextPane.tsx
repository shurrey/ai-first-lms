"use client";

import { PersonaSwitcher } from "./PersonaSwitcher";
import { CourseSelector } from "./CourseSelector";
import { useSession } from "@/lib/session-context";

export function ContextPane() {
  const { sessionId } = useSession();

  return (
    <nav className="flex h-full flex-col overflow-y-auto border-r border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Context
      </h2>
      <div className="space-y-4">
        <PersonaSwitcher />
        <CourseSelector />
      </div>
      {sessionId && (
        <div className="mt-4 rounded-lg border border-border bg-card p-3">
          <p className="text-xs text-muted-foreground">Session</p>
          <p className="truncate text-xs font-mono text-foreground/70">
            {sessionId}
          </p>
        </div>
      )}
    </nav>
  );
}
