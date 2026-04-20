"use client";

import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { useSession } from "./session-context";
import { useEventStream, type TurnState } from "./use-event-stream";
import type { BriefCardPayload } from "./events";

interface TurnContextValue extends TurnState {
  activeTurnId: string | null;
  briefCardData: BriefCardPayload | null;
  startTurn: (turnId: string) => void;
}

const TurnContext = createContext<TurnContextValue | null>(null);

export function TurnProvider({ children }: { children: React.ReactNode }) {
  const { sessionId, briefTurnId } = useSession();
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [briefCardData, setBriefCardData] = useState<BriefCardPayload | null>(null);

  // When briefTurnId arrives, start streaming it
  useEffect(() => {
    if (briefTurnId && !activeTurnId) {
      setActiveTurnId(briefTurnId);
    }
  }, [briefTurnId, activeTurnId]);

  const turnState = useEventStream(sessionId, activeTurnId);

  // Capture brief_card events from the stream
  useEffect(() => {
    if (turnState.briefCard) {
      setBriefCardData(turnState.briefCard);
    }
  }, [turnState.briefCard]);

  const startTurn = useCallback((turnId: string) => {
    setActiveTurnId(turnId);
  }, []);

  return (
    <TurnContext.Provider value={{ ...turnState, activeTurnId, briefCardData, startTurn }}>
      {children}
    </TurnContext.Provider>
  );
}

export function useTurn(): TurnContextValue {
  const ctx = useContext(TurnContext);
  if (!ctx) throw new Error("useTurn must be used within TurnProvider");
  return ctx;
}
