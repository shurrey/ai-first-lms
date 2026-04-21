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

export function PersonaSwitcher() {
  const { persona, courseId, setPersona, setSessionId, setBriefTurnId, resetSession } = useSession();

  const createSessionMutation = useMutation({
    mutationFn: ({ newPersona, course }: { newPersona: Persona; course: string }) =>
      createSession(newPersona, course),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setBriefTurnId(data.brief_turn_id ?? null);
    },
  });

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <label
        htmlFor="persona-select"
        className="mb-1 block text-xs text-muted-foreground"
      >
        Persona
      </label>
      <select
        id="persona-select"
        value={persona}
        onChange={(e) => {
          const newPersona = e.target.value as Persona;
          setPersona(newPersona);
          resetSession();
          // If a course is already selected, create a new session with the new persona
          if (courseId) {
            createSessionMutation.mutate({ newPersona, course: courseId });
          }
        }}
        className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/50"
      >
        {PERSONAS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
    </div>
  );
}
