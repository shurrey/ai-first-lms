"use client";

import { createContext, useContext, useCallback, useState } from "react";

export type Persona = "student" | "faculty" | "advisor" | "admin";

interface SessionState {
  persona: Persona;
  courseId: string | null;
  sessionId: string | null;
  briefTurnId: string | null;
  setPersona: (p: Persona) => void;
  setCourseId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  setBriefTurnId: (id: string | null) => void;
  resetSession: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona>("student");
  const [courseId, setCourseId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [briefTurnId, setBriefTurnId] = useState<string | null>(null);

  const resetSession = useCallback(() => {
    setSessionId(null);
    setBriefTurnId(null);
  }, []);

  return (
    <SessionContext.Provider
      value={{
        persona,
        courseId,
        sessionId,
        briefTurnId,
        setPersona,
        setCourseId,
        setSessionId,
        setBriefTurnId,
        resetSession,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
