"use client";

import { createContext, useContext, useCallback, useState } from "react";

export type Persona = "student" | "faculty" | "advisor" | "admin";

interface SessionState {
  persona: Persona;
  courseId: string | null;
  sessionId: string | null;
  personId: string | null;
  courseUuid: string | null;
  briefTurnId: string | null;
  setPersona: (p: Persona) => void;
  setCourseId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  setPersonId: (id: string | null) => void;
  setCourseUuid: (id: string | null) => void;
  setBriefTurnId: (id: string | null) => void;
  resetSession: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona>("student");
  const [courseId, setCourseId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [personId, setPersonId] = useState<string | null>(null);
  const [courseUuid, setCourseUuid] = useState<string | null>(null);
  const [briefTurnId, setBriefTurnId] = useState<string | null>(null);

  const resetSession = useCallback(() => {
    setSessionId(null);
    setPersonId(null);
    setCourseUuid(null);
    setBriefTurnId(null);
  }, []);

  return (
    <SessionContext.Provider
      value={{
        persona,
        courseId,
        sessionId,
        personId,
        courseUuid,
        briefTurnId,
        setPersona,
        setCourseId,
        setSessionId,
        setPersonId,
        setCourseUuid,
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
