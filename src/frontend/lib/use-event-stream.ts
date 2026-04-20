"use client";

import { useEffect, useCallback, useReducer } from "react";
import { createSSEClient } from "./sse";
import type {
  EventEnvelope,
  AgentTokenPayload,
  AgentToolCallPayload,
  AgentStartPayload,
  AgentResultPayload,
  FinalPayload,
  ErrorPayload,
  ClarifyPayload,
  ApprovalRequestPayload,
  ReasoningPayload,
  PlanPayload,
  BriefCardPayload,
} from "./events";

export interface TurnState {
  status: "idle" | "streaming" | "done" | "error";
  reasoning: string[];
  plan: PlanPayload | null;
  agentTokens: Map<string, string>; // step_id -> accumulated text
  toolCalls: AgentToolCallPayload[];
  activeAgents: Map<string, AgentStartPayload>;
  completedAgents: AgentResultPayload[];
  clarify: ClarifyPayload | null;
  approval: ApprovalRequestPayload | null;
  finalResult: FinalPayload | null;
  error: ErrorPayload | null;
  briefCard: BriefCardPayload | null;
}

type TurnAction =
  | { type: "start" }
  | { type: "event"; event: EventEnvelope }
  | { type: "reset" };

const initialState: TurnState = {
  status: "idle",
  reasoning: [],
  plan: null,
  agentTokens: new Map(),
  toolCalls: [],
  activeAgents: new Map(),
  completedAgents: [],
  clarify: null,
  approval: null,
  finalResult: null,
  error: null,
  briefCard: null,
};

function turnReducer(state: TurnState, action: TurnAction): TurnState {
  switch (action.type) {
    case "start":
      return { ...initialState, status: "streaming" };
    case "reset":
      return initialState;
    case "event": {
      const { event } = action;
      const payload = event.payload;

      switch (event.event) {
        case "reasoning":
          return {
            ...state,
            reasoning: [
              ...state.reasoning,
              (payload as ReasoningPayload).text,
            ],
          };

        case "plan":
          return { ...state, plan: payload as PlanPayload };

        case "agent_start": {
          const p = payload as AgentStartPayload;
          const activeAgents = new Map(state.activeAgents);
          activeAgents.set(p.step_id, p);
          return { ...state, activeAgents };
        }

        case "agent_token": {
          const p = payload as AgentTokenPayload;
          if (p.channel !== "response") return state;
          const agentTokens = new Map(state.agentTokens);
          const existing = agentTokens.get(p.step_id) ?? "";
          agentTokens.set(p.step_id, existing + p.delta);
          return { ...state, agentTokens };
        }

        case "agent_tool_call":
          return {
            ...state,
            toolCalls: [
              ...state.toolCalls,
              payload as AgentToolCallPayload,
            ],
          };

        case "agent_result": {
          const p = payload as AgentResultPayload;
          const activeAgents = new Map(state.activeAgents);
          activeAgents.delete(p.step_id);
          return {
            ...state,
            activeAgents,
            completedAgents: [...state.completedAgents, p],
          };
        }

        case "clarify":
          return { ...state, clarify: payload as ClarifyPayload };

        case "approval_request":
          return {
            ...state,
            approval: payload as ApprovalRequestPayload,
          };

        case "final":
          return {
            ...state,
            status: "done",
            finalResult: payload as FinalPayload,
          };

        case "error":
          return {
            ...state,
            status: "error",
            error: payload as ErrorPayload,
          };

        case "brief_card":
          return { ...state, briefCard: event.payload as BriefCardPayload };

        default:
          return state;
      }
    }
    default:
      return state;
  }
}

export function useEventStream(
  sessionId: string | null,
  turnId: string | null
) {
  const [state, dispatch] = useReducer(turnReducer, initialState);

  useEffect(() => {
    if (!sessionId || !turnId) return;

    dispatch({ type: "start" });

    const cleanup = createSSEClient({
      sessionId,
      turnId,
      onEvent: (event) => dispatch({ type: "event", event }),
      onError: (error) =>
        dispatch({
          type: "event",
          event: {
            event: "error",
            session_id: sessionId,
            turn_id: turnId,
            sequence: 0,
            timestamp: new Date().toISOString(),
            payload: {
              code: "internal",
              message: error.message,
              retriable: false,
            },
          },
        }),
    });

    return cleanup;
  }, [sessionId, turnId]);

  const reset = useCallback(() => dispatch({ type: "reset" }), []);

  return { ...state, reset };
}
