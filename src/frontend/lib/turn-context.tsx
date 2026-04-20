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

  // When session changes, reset everything
  useEffect(() => {
    setActiveTurnId(null);
    setBriefCardData(null);
  }, [sessionId]);

  // When briefTurnId arrives (new session), start streaming it
  useEffect(() => {
    if (briefTurnId && (!activeTurnId || activeTurnId.startsWith("brief-"))) {
      setActiveTurnId(briefTurnId);
    }
  }, [briefTurnId]);

  const turnState = useEventStream(sessionId, activeTurnId);

  // Capture brief_card events from the stream
  useEffect(() => {
    if (turnState.briefCard) {
      setBriefCardData(turnState.briefCard);
    }
  }, [turnState.briefCard]);

  const startTurn = useCallback((turnId: string) => {
    // Reset turn state BEFORE changing activeTurnId to prevent stale
    // finalResult from the previous turn leaking into the next render cycle
    turnState.reset();
    setActiveTurnId(turnId);
  }, [turnState.reset]);

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
