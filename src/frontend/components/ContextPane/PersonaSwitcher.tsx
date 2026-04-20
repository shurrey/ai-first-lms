"use client";

import { useSession, type Persona } from "@/lib/session-context";

const PERSONAS: { value: Persona; label: string }[] = [
  { value: "student", label: "Student" },
  { value: "faculty", label: "Faculty" },
  { value: "advisor", label: "Advisor" },
  { value: "admin", label: "Admin" },
];

export function PersonaSwitcher() {
  const { persona, setPersona, resetSession } = useSession();

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
          setPersona(e.target.value as Persona);
          resetSession();
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
