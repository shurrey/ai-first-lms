"use client";

import { createContext, useContext, useState, useCallback } from "react";
import { useSession } from "./session-context";
import { useEventStream, type TurnState } from "./use-event-stream";

interface TurnContextValue extends TurnState {
  activeTurnId: string | null;
  startTurn: (turnId: string) => void;
}

const TurnContext = createContext<TurnContextValue | null>(null);

export function TurnProvider({ children }: { children: React.ReactNode }) {
  const { sessionId } = useSession();
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const turnState = useEventStream(sessionId, activeTurnId);

  const startTurn = useCallback((turnId: string) => {
    setActiveTurnId(turnId);
  }, []);

  return (
    <TurnContext.Provider value={{ ...turnState, activeTurnId, startTurn }}>
      {children}
    </TurnContext.Provider>
  );
}

export function useTurn(): TurnContextValue {
  const ctx = useContext(TurnContext);
  if (!ctx) throw new Error("useTurn must be used within TurnProvider");
  return ctx;
}
