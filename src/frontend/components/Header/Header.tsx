"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "@/lib/session-context";
import { useAuth } from "@/lib/auth-context";
import { ApiError, createSession } from "@/lib/api";
import { ROLE_LABELS, switchRole, type Me, type PersonRole } from "@/lib/auth";
import { AccountMenu } from "./AccountMenu";

/** Advisor and admin have no enrollments; they act across their whole scope instead. */
const SCOPE_ENTRY: Partial<Record<PersonRole, string>> = {
  advisor: "All my students",
  admin: "Institution",
};

const ALL_COURSES = "all";

function defaultCourseFor(me: Me, previousCourseId: string | null): string | null {
  if (SCOPE_ENTRY[me.active_role]) return ALL_COURSES;
  if (previousCourseId && me.enrollments.some((e) => e.course_id === previousCourseId)) {
    return previousCourseId;
  }
  return me.enrollments.length === 1 ? me.enrollments[0].course_id : null;
}

export function Header() {
  const { me, setMe, refresh } = useAuth();
  const { courseId, setCourseId, setSessionId, setCourseUuid, setBriefTurnId, resetSession } =
    useSession();
  const [announcement, setAnnouncement] = useState("");

  const scopeLabel = SCOPE_ENTRY[me.active_role];
  const canListCourses = me.capabilities.course_list !== undefined;

  const createSessionMutation = useMutation({
    mutationFn: (c: string) => createSession(c),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setCourseUuid(data.course_uuid ?? null);
      setBriefTurnId(data.brief_turn_id ?? null);
    },
  });

  const startSession = (newCourseId: string | null) => {
    resetSession();
    setCourseId(newCourseId);
    if (newCourseId) createSessionMutation.mutate(newCourseId);
  };

  const queryClient = useQueryClient();
  const switchRoleMutation = useMutation({
    mutationFn: switchRole,
    onSuccess: async (newMe) => {
      // Cached responses were fetched under the previous role's access.
      queryClient.removeQueries({ queryKey: ["api"] });
      setMe(newMe);
      setAnnouncement(`Switched to ${ROLE_LABELS[newMe.active_role]}.`);
      startSession(defaultCourseFor(newMe, courseId));
      await refresh();
    },
    onError: () => setAnnouncement("Couldn't switch role. Please try again."),
  });

  const sessionError = createSessionMutation.error;

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      <h1 className="text-sm font-semibold tracking-tight">AI-First LMS</h1>

      {canListCourses && (
        <>
          <span className="text-border" aria-hidden="true">·</span>
          <label htmlFor="course-select" className="sr-only">
            Course
          </label>
          <select
            id="course-select"
            value={courseId ?? ""}
            onChange={(e) => startSession(e.target.value || null)}
            className="rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">Select a course...</option>
            {scopeLabel && <option value={ALL_COURSES}>{scopeLabel}</option>}
            {me.enrollments.map((e) => (
              <option key={e.course_id} value={e.course_id}>
                {e.title}
              </option>
            ))}
          </select>
          {createSessionMutation.isPending && (
            <span role="status" className="text-xs text-muted-foreground">
              Starting session…
            </span>
          )}
          {sessionError && (
            <span role="alert" className="text-xs text-destructive">
              {sessionError instanceof ApiError && sessionError.isForbidden
                ? "You don't have access to this course."
                : "Couldn't start a session. Please try again."}
            </span>
          )}
        </>
      )}

      <div className="ml-auto flex items-center gap-2">
        <span role="status" className="sr-only">
          {announcement}
        </span>
        <AccountMenu
          onSwitchRole={(role) => switchRoleMutation.mutate(role)}
          switching={switchRoleMutation.isPending}
        />
      </div>
    </header>
  );
}
