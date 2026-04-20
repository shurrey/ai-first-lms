"use client";

import { useSession } from "@/lib/session-context";
import { useMutation } from "@tanstack/react-query";
import { createSession } from "@/lib/api";

const MOCK_COURSES = [
  { id: "cs101", name: "CS 101 — Intro to Computer Science" },
  { id: "math201", name: "MATH 201 — Linear Algebra" },
  { id: "eng102", name: "ENG 102 — Academic Writing" },
  { id: "bio150", name: "BIO 150 — General Biology" },
];

export function CourseSelector() {
  const { persona, courseId, setCourseId, setSessionId } = useSession();

  const createSessionMutation = useMutation({
    mutationFn: (selectedCourseId: string) =>
      createSession(persona, selectedCourseId),
    onSuccess: (data) => {
      setSessionId(data.session_id);
    },
  });

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <label
        htmlFor="course-select"
        className="mb-1 block text-xs text-muted-foreground"
      >
        Course
      </label>
      <select
        id="course-select"
        value={courseId ?? ""}
        onChange={(e) => {
          const id = e.target.value || null;
          setCourseId(id);
          if (id) {
            createSessionMutation.mutate(id);
          }
        }}
        className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/50"
      >
        <option value="">Select a course...</option>
        {MOCK_COURSES.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {createSessionMutation.isPending && (
        <p className="mt-1 text-xs text-muted-foreground">
          Creating session...
        </p>
      )}
      {createSessionMutation.isError && (
        <p className="mt-1 text-xs text-destructive">
          Failed to create session
        </p>
      )}
    </div>
  );
}
