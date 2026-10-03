"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { StagedCommit } from "./grade-commit";
import type { AlignmentProposal } from "./alignment";

interface AiPanelState {
  isOpen: boolean;
  /** Prompts handed to the panel by `open(prompt)`, oldest first; the panel sends them one turn at a time. */
  queuedPrompts: string[];
  /** Increments each time a panel turn ends, so pages can refresh what the turn may have changed. */
  turnsCompleted: number;
  /** Final scores and closing comment entered on the review page, by submission id, so the
   * grade_commit approval card can start from them. */
  stagedCommits: Record<string, StagedCommit>;
  stageCommit: (submissionId: string, commit: StagedCommit) => void;
  /** Newest alignment proposal returned by a panel turn, by assignment node. */
  alignmentProposals: Record<string, AlignmentProposal>;
  publishProposal: (proposal: AlignmentProposal) => void;
  open: (prompt?: string) => void;
  close: () => void;
  takePrompt: () => void;
  markTurnCompleted: () => void;
}

const AiPanelContext = createContext<AiPanelState | null>(null);

export function AiPanelProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [queuedPrompts, setQueuedPrompts] = useState<string[]>([]);
  const [turnsCompleted, setTurnsCompleted] = useState(0);
  const [stagedCommits, setStagedCommits] = useState<Record<string, StagedCommit>>({});
  const [alignmentProposals, setAlignmentProposals] = useState<Record<string, AlignmentProposal>>({});

  const open = useCallback((prompt?: string) => {
    if (prompt) setQueuedPrompts((q) => [...q, prompt]);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    setQueuedPrompts([]);
  }, []);
  const takePrompt = useCallback(() => setQueuedPrompts((q) => q.slice(1)), []);
  const markTurnCompleted = useCallback(() => setTurnsCompleted((n) => n + 1), []);
  const stageCommit = useCallback((submissionId: string, commit: StagedCommit) => {
    setStagedCommits((s) => ({ ...s, [submissionId]: commit }));
  }, []);
  const publishProposal = useCallback((proposal: AlignmentProposal) => {
    setAlignmentProposals((s) => ({ ...s, [proposal.assignment_node]: proposal }));
  }, []);

  return (
    <AiPanelContext.Provider value={{
      isOpen, queuedPrompts, turnsCompleted, stagedCommits, stageCommit, alignmentProposals, publishProposal,
      open, close, takePrompt, markTurnCompleted,
    }}>
      {children}
    </AiPanelContext.Provider>
  );
}

export function useAiPanel() {
  const ctx = useContext(AiPanelContext);
  if (!ctx) throw new Error("useAiPanel must be used within AiPanelProvider");
  return ctx;
}
