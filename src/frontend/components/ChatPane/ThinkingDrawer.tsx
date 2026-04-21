"use client";

import { useState } from "react";
import type { AgentToolCallPayload } from "@/lib/events";

interface ThinkingStep {
  type: "reasoning" | "tool_call" | "thinking";
  text: string;
  tool?: string;
  latencyMs?: number;
  success?: boolean;
}

interface ThinkingDrawerProps {
  steps: ThinkingStep[];
  isStreaming: boolean;
  tokenCount?: number;
  toolCallCount?: number;
}

export function ThinkingDrawer({ steps, isStreaming, tokenCount, toolCallCount }: ThinkingDrawerProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0) return null;

  // While streaming, show expanded live view
  if (isStreaming) {
    return (
      <div className="mb-2 mr-[20%] space-y-1">
        {steps.map((step, i) => (
          <ThinkingStepBlock key={i} step={step} />
        ))}
      </div>
    );
  }

  // After completion, show collapsible drawer
  const toolCalls = steps.filter((s) => s.type === "tool_call").length;
  const summary = `${toolCalls} tool call${toolCalls !== 1 ? "s" : ""}${tokenCount ? ` · ${Math.round(tokenCount / 1000)}k tokens` : ""}`;

  return (
    <div className="mb-2 mr-[20%] overflow-hidden rounded-lg border border-purple-200 bg-purple-50/50 dark:border-purple-900 dark:bg-purple-950/20">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs"
      >
        <span className="text-[10px] text-purple-500">{expanded ? "▼" : "▶"}</span>
        <span className="font-medium text-purple-700 dark:text-purple-300">Thinking</span>
        <span className="ml-auto text-[10px] text-muted-foreground">{summary}</span>
      </button>
      {expanded && (
        <div className="border-t border-purple-200 px-3 py-2 dark:border-purple-900">
          <div className="space-y-0.5">
            {steps.map((step, i) => (
              <ThinkingStepBlock key={i} step={step} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ThinkingStepBlock({ step }: { step: ThinkingStep }) {
  if (step.type === "tool_call") {
    return (
      <div className="flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-950/30">
        <span>⚡</span>
        <span>{step.tool}</span>
        {step.latencyMs !== undefined && (
          <span className="text-muted-foreground">— {Math.round(step.latencyMs)}ms</span>
        )}
        <span>{step.success ? "✓" : "✗"}</span>
      </div>
    );
  }

  const icon = step.type === "thinking" ? "💬" : "🔍";
  return (
    <div className="flex items-start gap-1.5 rounded px-2 py-0.5 text-[10px] text-purple-700 bg-purple-50/50 dark:text-purple-300 dark:bg-purple-950/20 italic">
      <span className="shrink-0">{icon}</span>
      <span>{step.text}</span>
    </div>
  );
}

/** Build ThinkingStep array from turn state */
export function buildThinkingSteps(
  reasoning: string[],
  toolCalls: AgentToolCallPayload[],
  thinkingMessages: string[],
): ThinkingStep[] {
  const steps: ThinkingStep[] = [];
  for (const r of reasoning) {
    steps.push({ type: "reasoning", text: r });
  }
  let thinkIdx = 0;
  for (const tc of toolCalls) {
    if (thinkIdx < thinkingMessages.length) {
      steps.push({ type: "thinking", text: thinkingMessages[thinkIdx] });
      thinkIdx++;
    }
    steps.push({
      type: "tool_call",
      text: tc.tool,
      tool: tc.tool,
      latencyMs: tc.latency_ms,
      success: tc.success,
    });
  }
  while (thinkIdx < thinkingMessages.length) {
    steps.push({ type: "thinking", text: thinkingMessages[thinkIdx] });
    thinkIdx++;
  }
  return steps;
}
