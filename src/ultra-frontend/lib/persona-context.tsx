"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { Persona } from "./types";

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
  setPersona: (p: Persona) => void;
}

const PersonaContext = createContext<PersonaState | null>(null);

export function PersonaProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersonaRaw] = useState<Persona>("faculty");

  const setPersona = useCallback((p: Persona) => {
    setPersonaRaw(p);
  }, []);

  const user = PERSONA_USERS[persona];

  return (
    <PersonaContext.Provider value={{ persona, userName: user.name, userRole: user.role, setPersona }}>
      {children}
    </PersonaContext.Provider>
  );
}

export function usePersona() {
  const ctx = useContext(PersonaContext);
  if (!ctx) throw new Error("usePersona must be used within PersonaProvider");
  return ctx;
}
