"use client";

import { createContext, useContext, useState, useCallback } from "react";

interface AiPanelState {
  isOpen: boolean;
  initialPrompt: string | null;
  open: (prompt?: string) => void;
  close: () => void;
  clearPrompt: () => void;
}

const AiPanelContext = createContext<AiPanelState | null>(null);

export function AiPanelProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [initialPrompt, setInitialPrompt] = useState<string | null>(null);

  const open = useCallback((prompt?: string) => {
    if (prompt) setInitialPrompt(prompt);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => setIsOpen(false), []);
  const clearPrompt = useCallback(() => setInitialPrompt(null), []);

  return (
    <AiPanelContext.Provider value={{ isOpen, initialPrompt, open, close, clearPrompt }}>
      {children}
    </AiPanelContext.Provider>
  );
}

export function useAiPanel() {
  const ctx = useContext(AiPanelContext);
  if (!ctx) throw new Error("useAiPanel must be used within AiPanelProvider");
  return ctx;
}
