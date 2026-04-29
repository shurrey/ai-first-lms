"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { Persona } from "./types";
import { API_BASE } from "./api";

const PERSONA_USERS: Record<Persona, { name: string; role: string }> = {
  faculty: { name: "Dr. Maria Torres", role: "Faculty" },
  student: { name: "Emma Smith", role: "Student" },
  advisor: { name: "Ms. Adaeze Okafor", role: "Advisor" },
  admin: { name: "Dr. Richard Hayes", role: "Admin" },
};

interface PersonaState {
  persona: Persona;
  userName: string;
  userRole: string;
  sessionId: string | null;
  personId: string | null;
  setPersona: (p: Persona) => void;
  ensureSession: (courseId: string) => Promise<{ sessionId: string; personId: string | null }>;
}

const PersonaContext = createContext<PersonaState | null>(null);

export function PersonaProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersonaRaw] = useState<Persona>("faculty");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [personId, setPersonId] = useState<string | null>(null);
  const [sessionCourse, setSessionCourse] = useState<string | null>(null);
  const [sessionPersona, setSessionPersona] = useState<Persona | null>(null);

  const setPersona = useCallback((p: Persona) => {
    setPersonaRaw(p);
    // Invalidate session on persona change
    setSessionId(null);
    setPersonId(null);
    setSessionCourse(null);
    setSessionPersona(null);
  }, []);

  const ensureSession = useCallback(async (courseId: string): Promise<{ sessionId: string; personId: string | null }> => {
    // Reuse session if same persona + course
    if (sessionId && sessionCourse === courseId && sessionPersona === persona) {
      return { sessionId, personId };
    }
    const res = await fetch(`${API_BASE}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona, course_id: courseId }),
    });
    const data = await res.json();
    setSessionId(data.session_id);
    setPersonId(data.person_id ?? null);
    setSessionCourse(courseId);
    setSessionPersona(persona);
    return { sessionId: data.session_id, personId: data.person_id ?? null };
  }, [persona, sessionId, personId, sessionCourse, sessionPersona]);

  const user = PERSONA_USERS[persona];

  return (
    <PersonaContext.Provider value={{ persona, userName: user.name, userRole: user.role, sessionId, personId, setPersona, ensureSession }}>
      {children}
    </PersonaContext.Provider>
  );
}

export function usePersona() {
  const ctx = useContext(PersonaContext);
  if (!ctx) throw new Error("usePersona must be used within PersonaProvider");
  return ctx;
}
