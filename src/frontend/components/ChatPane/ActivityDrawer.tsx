"use client";

import { useState } from "react";
import type { AgentToolCallPayload } from "@/lib/events";

export interface ActivityStep {
  type: "reasoning" | "tool_call" | "note";
  text: string;
  tool?: string;
  latencyMs?: number;
  success?: boolean;
}

interface ActivityDrawerProps {
  steps: ActivityStep[];
  isStreaming: boolean;
  tokenCount?: number;
}

/** Live list of steps while the turn streams; afterwards a collapsed "What ran" disclosure. */
export function ActivityDrawer({ steps, isStreaming, tokenCount }: ActivityDrawerProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0) return null;

  if (isStreaming) {
    return (
      <div className="mb-2 mr-[20%] space-y-1">
        {steps.map((step, i) => (
          <ActivityStepBlock key={i} step={step} />
        ))}
      </div>
    );
  }

  const toolCalls = steps.filter((s) => s.type === "tool_call").length;
  const summary = `${toolCalls} tool call${toolCalls !== 1 ? "s" : ""}${tokenCount ? ` · ${Math.round(tokenCount / 1000)}k tokens` : ""}`;

  return (
    <div className="mb-2 mr-[20%] overflow-hidden rounded-lg border border-purple-200 bg-purple-50/50 dark:border-purple-900 dark:bg-purple-950/20">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs"
      >
        <span aria-hidden="true" className="text-[10px] text-purple-500">{expanded ? "▼" : "▶"}</span>
        <span className="font-medium text-purple-700 dark:text-purple-300">What ran</span>
        <span className="ml-auto text-[10px] text-muted-foreground">{summary}</span>
      </button>
      {expanded && (
        <div className="border-t border-purple-200 px-3 py-2 dark:border-purple-900">
          <div className="space-y-0.5">
            {steps.map((step, i) => (
              <ActivityStepBlock key={i} step={step} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ActivityStepBlock({ step }: { step: ActivityStep }) {
  if (step.type === "tool_call") {
    return (
      <div className="flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-950/30">
        <span aria-hidden="true">⚡</span>
        <span>{step.tool}</span>
        {step.latencyMs !== undefined && (
          <span className="text-muted-foreground">— {Math.round(step.latencyMs)}ms</span>
        )}
        <span role="img" aria-label={step.success ? "succeeded" : "failed"}>{step.success ? "✓" : "✗"}</span>
      </div>
    );
  }

  const icon = step.type === "note" ? "💬" : "🔍";
  return (
    <div className="flex items-start gap-1.5 rounded px-2 py-0.5 text-[10px] text-purple-700 bg-purple-50/50 dark:text-purple-300 dark:bg-purple-950/20 italic">
      <span aria-hidden="true" className="shrink-0">{icon}</span>
      <span>{step.text}</span>
    </div>
  );
}

/** Interleaves progress-note events between tool calls in arrival order. */
export function buildActivitySteps(
  reasoning: string[],
  toolCalls: AgentToolCallPayload[],
  notes: string[],
): ActivityStep[] {
  const steps: ActivityStep[] = [];
  for (const r of reasoning) {
    steps.push({ type: "reasoning", text: r });
  }
  let noteIdx = 0;
  for (const tc of toolCalls) {
    if (noteIdx < notes.length) {
      steps.push({ type: "note", text: notes[noteIdx] });
      noteIdx++;
    }
    steps.push({
      type: "tool_call",
      text: tc.tool,
      tool: tc.tool,
      latencyMs: tc.latency_ms,
      success: tc.success,
    });
  }
  while (noteIdx < notes.length) {
    steps.push({ type: "note", text: notes[noteIdx] });
    noteIdx++;
  }
  return steps;
}
