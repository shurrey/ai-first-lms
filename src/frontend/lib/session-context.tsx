"use client";

import { createContext, useContext, useCallback, useState } from "react";

/** Orchestrator conversation state. Identity and role live in auth-context (/me). */
interface SessionState {
  courseId: string | null;
  sessionId: string | null;
  courseUuid: string | null;
  briefTurnId: string | null;
  setCourseId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  setCourseUuid: (id: string | null) => void;
  setBriefTurnId: (id: string | null) => void;
  resetSession: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [courseId, setCourseId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [courseUuid, setCourseUuid] = useState<string | null>(null);
  const [briefTurnId, setBriefTurnId] = useState<string | null>(null);

  const resetSession = useCallback(() => {
    setSessionId(null);
    setCourseUuid(null);
    setBriefTurnId(null);
  }, []);

  return (
    <SessionContext.Provider
      value={{
        courseId,
        sessionId,
        courseUuid,
        briefTurnId,
        setCourseId,
        setSessionId,
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
