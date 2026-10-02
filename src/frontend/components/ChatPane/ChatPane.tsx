"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import { converse } from "@/lib/api";
import { ActivityDrawer, buildActivitySteps } from "./ActivityDrawer";
import { MessageBubble, type ChatMessage } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { ClarifyPrompt } from "./ClarifyPrompt";
import { ErrorDisplay } from "./ErrorDisplay";
import { ApprovalGate } from "@/components/ApprovalGate";
import { CanvasRouter } from "@/components/Canvas/CanvasRouter";
import { AiGeneratedLabel } from "@/components/common/AiGeneratedLabel";
import { artifactAiActionId, buildTurnSources } from "@/lib/provenance";

export function ChatPane() {
  const { sessionId } = useSession();
  const turnState = useTurn();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [decidedApprovalId, setDecidedApprovalId] = useState<string | null>(null);
  const pendingApproval =
    turnState.approval && turnState.approval.approval_id !== decidedApprovalId
      && turnState.status === "streaming"
      ? turnState.approval
      : null;

  // Track which turn IDs we've already rendered messages for
  const renderedRef = useRef(new Set<string>());
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change or activity updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, turnState.status, turnState.reasoning, turnState.toolCalls]);

  // Clear messages and rendered set when session changes
  useEffect(() => {
    setMessages([]);
    renderedRef.current = new Set();
  }, [sessionId]);

  // When the SSE stream produces a final result, add the assistant message
  useEffect(() => {
    if (
      turnState.status === "done" &&
      turnState.finalResult &&
      turnState.activeTurnId &&
      !renderedRef.current.has(turnState.activeTurnId)
    ) {
      renderedRef.current.add(turnState.activeTurnId);
      const msgId = `assistant-${turnState.activeTurnId}`;
      setMessages((prev) => {
        const withoutPlaceholder = prev.filter(
          (m) => m.id !== `streaming-${turnState.activeTurnId}`
        );
        return [
          ...withoutPlaceholder,
          {
            id: msgId,
            role: "assistant" as const,
            content: turnState.finalResult!.answer_markdown,
            timestamp: new Date().toISOString(),
            followUps: turnState.finalResult!.follow_ups,
            artifacts: turnState.finalResult!.artifacts,
            provenance: {
              aiActionIds: turnState.finalResult!.ai_action_ids ?? [],
              sources: buildTurnSources(turnState.completedAgents, turnState.toolCalls),
            },
          },
        ];
      });
    }
  }, [turnState.status, turnState.finalResult, turnState.activeTurnId, turnState.completedAgents, turnState.toolCalls]);

  // While streaming, show accumulated agent tokens as a live message
  useEffect(() => {
    if (turnState.status !== "streaming") return;
    const allTokens = Array.from(turnState.agentTokens.values()).join("");
    if (!allTokens) return;

    setMessages((prev) => {
      const idx = prev.findIndex(
        (m) => m.id === `streaming-${turnState.activeTurnId}`
      );
      const streamMsg: ChatMessage = {
        id: `streaming-${turnState.activeTurnId}`,
        role: "assistant",
        content: allTokens,
        timestamp: new Date().toISOString(),
      };
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = streamMsg;
        return updated;
      }
      return [...prev, streamMsg];
    });
  }, [turnState.status, turnState.agentTokens, turnState.activeTurnId]);

  // Handle errors from the stream
  useEffect(() => {
    if (turnState.status === "error" && turnState.error) {
      setMessages((prev) => {
        const withoutPlaceholder = prev.filter(
          (m) => m.id !== `streaming-${turnState.activeTurnId}`
        );
        return [
          ...withoutPlaceholder,
          {
            id: `error-${turnState.activeTurnId}`,
            role: "assistant" as const,
            content: `Error: ${turnState.error!.message}`,
            timestamp: new Date().toISOString(),
          },
        ];
      });
    }
  }, [turnState.status, turnState.error, turnState.activeTurnId]);

  const activitySteps = buildActivitySteps(
    turnState.reasoning,
    turnState.toolCalls,
    turnState.thinkingMessages,
  );
  const lastTool = turnState.toolCalls[turnState.toolCalls.length - 1]?.tool;
  const turnSources = buildTurnSources(turnState.completedAgents, turnState.toolCalls);

  const converseMutation = useMutation({
    mutationFn: (message: string) => {
      if (!sessionId) throw new Error("No active session");
      return converse(sessionId, message);
    },
    onSuccess: (data) => {
      turnState.startTurn(data.turn_id);
    },
    onError: () => {
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: "Failed to send message. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    },
  });

  const handleSend = useCallback(
    (text: string) => {
      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      converseMutation.mutate(text);
    },
    [converseMutation]
  );


  return (
    <main className="flex h-full flex-col overflow-hidden">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4"><div className="mx-auto max-w-3xl space-y-2">
        {messages.length === 0 && turnState.status === "idle" && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">Start a conversation with the AI-First LMS.</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {activitySteps.length > 0 && (
          <ActivityDrawer
            steps={activitySteps}
            isStreaming={turnState.status === "streaming"}
            tokenCount={turnState.finalResult?.tokens}
          />
        )}
        <p role="status" className="text-xs text-muted-foreground">
          {turnState.status === "streaming" && !pendingApproval && !turnState.clarify
            ? lastTool
              ? `Running: ${lastTool}`
              : "Working…"
            : ""}
        </p>
      </div></div>

      {pendingApproval && (
        <section aria-label="Approval needed" className="shrink-0 px-4 pb-2">
          <div className="mx-auto max-w-2xl space-y-3">
            <CanvasRouter
              artifact={{
                artifact_id: pendingApproval.approval_id,
                type: pendingApproval.artifact_type,
                data: pendingApproval.preview,
              }}
              status="awaiting_approval"
            />
            <AiGeneratedLabel
              aiActionIds={(() => {
                const id = artifactAiActionId(pendingApproval.preview);
                return id ? [id] : [];
              })()}
              sources={turnSources}
            />
            <ApprovalGate
              approvalId={pendingApproval.approval_id}
              action={pendingApproval.action}
              preview={pendingApproval.preview}
              onDecided={() => setDecidedApprovalId(pendingApproval.approval_id)}
            />
          </div>
        </section>
      )}

      {/* Clarification prompt */}
      {turnState.clarify && (
        <div className="shrink-0 px-4 pb-2">
          <div className="mx-auto max-w-2xl">
            <ClarifyPrompt clarify={turnState.clarify} />
          </div>
        </div>
      )}

      {/* Error with retry */}
      {turnState.status === "error" && turnState.error && (
        <div className="shrink-0 px-4 pb-2">
          <div className="mx-auto max-w-2xl">
            <ErrorDisplay
              error={turnState.error}
              onRetry={
                turnState.error.retriable
                  ? () => {
                      const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
                      if (lastUserMsg) handleSend(lastUserMsg.content);
                    }
                  : undefined
              }
            />
          </div>
        </div>
      )}

      <ChatInput
        onSend={handleSend}
        disabled={!sessionId}
        loading={converseMutation.isPending || turnState.status === "streaming"}
      />
    </main>
  );
}
