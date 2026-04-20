"use client";

import type {
  AgentStartPayload,
  AgentToolCallPayload,
  AgentResultPayload,
} from "@/lib/events";

interface AgentNodeProps {
  agent: AgentStartPayload;
  toolCalls: AgentToolCallPayload[];
  result: AgentResultPayload | undefined;
  streamedText: string | undefined;
}

export function AgentNode({
  agent,
  toolCalls,
  result,
  streamedText,
}: AgentNodeProps) {
  const isActive = !result;

  return (
    <div className="ml-3 border-l-2 border-border pl-3">
      <div className="flex items-center gap-2 py-1">
        <span
          className={`inline-block size-2 rounded-full ${
            isActive ? "animate-pulse bg-blue-500" : result?.success ? "bg-green-500" : "bg-red-500"
          }`}
        />
        <span className="text-xs font-medium">{agent.agent}</span>
        {result && (
          <span className="text-xs text-muted-foreground">
            {result.tokens} tokens
          </span>
        )}
      </div>

      {/* Tool calls — tool name MUST be visible (transparency principle) */}
      {toolCalls.map((tc, i) => (
        <div key={i} className="ml-4 flex items-center gap-1.5 py-0.5">
          <span
            className={`text-xs ${tc.success ? "text-green-600" : "text-red-600"}`}
          >
            {tc.success ? "+" : "x"}
          </span>
          <code className="text-xs font-mono text-muted-foreground">
            {tc.tool}
          </code>
          <span className="text-xs text-muted-foreground/60">
            {tc.latency_ms}ms
          </span>
        </div>
      ))}

      {/* Streamed response preview */}
      {isActive && streamedText && (
        <p className="ml-4 mt-1 line-clamp-2 text-xs text-muted-foreground italic">
          {streamedText.slice(0, 120)}
          {streamedText.length > 120 && "..."}
        </p>
      )}
    </div>
  );
}
