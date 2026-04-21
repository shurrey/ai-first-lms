"use client";

import { useSession, type Persona } from "@/lib/session-context";
import { useMutation } from "@tanstack/react-query";
import { createSession } from "@/lib/api";

const PERSONAS: { value: Persona; label: string }[] = [
  { value: "student", label: "Student" },
  { value: "faculty", label: "Faculty" },
  { value: "advisor", label: "Advisor" },
  { value: "admin", label: "Admin" },
];

const COURSES = [
  { id: "cs101", name: "CS 101 — Intro to Computer Science" },
  { id: "math201", name: "MATH 201 — Linear Algebra" },
  { id: "eng102", name: "ENG 102 — Academic Writing" },
  { id: "bio150", name: "BIO 150 — General Biology" },
];

export function Header() {
  const {
    persona, courseId, sessionId,
    setPersona, setCourseId, setSessionId, setBriefTurnId, resetSession,
  } = useSession();

  const createSessionMutation = useMutation({
    mutationFn: ({ p, c }: { p: Persona; c: string }) => createSession(p, c),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setBriefTurnId(data.brief_turn_id ?? null);
    },
  });

  const handleCourseChange = (newCourseId: string) => {
    setCourseId(newCourseId || null);
    if (newCourseId) {
      createSessionMutation.mutate({ p: persona, c: newCourseId });
    }
  };

  const handlePersonaChange = (newPersona: Persona) => {
    setPersona(newPersona);
    resetSession();
    // For advisor/admin, auto-select first course if none selected
    const effectiveCourse = courseId ?? ((newPersona === "advisor" || newPersona === "admin") ? COURSES[0].id : null);
    if (effectiveCourse) {
      if (!courseId) setCourseId(effectiveCourse);
      createSessionMutation.mutate({ p: newPersona, c: effectiveCourse });
    }
  };

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      <h1 className="text-sm font-semibold tracking-tight">AI-First LMS</h1>
      <span className="text-border">·</span>

      <select
        value={courseId ?? ""}
        onChange={(e) => handleCourseChange(e.target.value)}
        className="rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
      >
        <option value="">Select a course...</option>
        {COURSES.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>

      <div className="ml-auto flex items-center gap-2">
        <select
          value={persona}
          onChange={(e) => handlePersonaChange(e.target.value as Persona)}
          className="rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
        >
          {PERSONAS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>

      </div>
    </header>
  );
}
