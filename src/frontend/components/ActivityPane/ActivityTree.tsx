"use client";

import { useTurn } from "@/lib/turn-context";
import { AgentNode } from "./ActivityNode";

export function ActivityTree() {
  const turn = useTurn();

  if (turn.status === "idle") {
    return (
      <p className="text-xs text-muted-foreground">
        Agent activity and results will appear here.
      </p>
    );
  }

  // Collect all agent step_ids (active + completed)
  const allStepIds = new Set<string>();
  for (const [stepId] of turn.activeAgents) allStepIds.add(stepId);
  for (const r of turn.completedAgents) allStepIds.add(r.step_id);

  return (
    <div className="space-y-2">
      {/* Reasoning steps */}
      {turn.reasoning.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground">
            Reasoning
          </p>
          {turn.reasoning.map((text, i) => (
            <p key={i} className="ml-3 text-xs text-muted-foreground">
              {text}
            </p>
          ))}
        </div>
      )}

      {/* Plan */}
      {turn.plan && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground">
            Plan ({turn.plan.strategy})
          </p>
          {turn.plan.steps.map((step) => (
            <p key={step.step_id} className="ml-3 text-xs text-muted-foreground">
              {step.agent}: {step.input_summary}
            </p>
          ))}
        </div>
      )}

      {/* Agent nodes */}
      {Array.from(allStepIds).map((stepId) => {
        const active = turn.activeAgents.get(stepId);
        const completed = turn.completedAgents.find(
          (r) => r.step_id === stepId
        );
        const agentInfo = active ?? {
          step_id: stepId,
          agent: completed?.agent ?? "unknown",
          inputs: {},
        };
        const toolCalls = turn.toolCalls.filter(
          (tc) => tc.step_id === stepId
        );
        const streamedText = turn.agentTokens.get(stepId);

        return (
          <AgentNode
            key={stepId}
            agent={agentInfo}
            toolCalls={toolCalls}
            result={completed}
            streamedText={streamedText}
          />
        );
      })}

      {/* Status indicator */}
      {turn.status === "streaming" && (
        <p className="text-xs text-blue-500 animate-pulse">Streaming...</p>
      )}
      {turn.status === "done" && (
        <p className="text-xs text-green-600">Complete</p>
      )}
      {turn.status === "error" && (
        <p className="text-xs text-red-600">
          Error: {turn.error?.message}
        </p>
      )}
    </div>
  );
}
