"use client";

import { useState, useCallback, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import { converse } from "@/lib/api";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { ClarifyPrompt } from "./ClarifyPrompt";
import { ErrorDisplay } from "./ErrorDisplay";
import type { ChatMessage } from "./MessageBubble";

export function ChatPane() {
  const { sessionId } = useSession();
  const turnState = useTurn();
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  // Clear messages when session changes (course switch)
  useEffect(() => {
    setMessages([]);
  }, [sessionId]);

  // When the SSE stream produces a final result, add the assistant message
  useEffect(() => {
    if (turnState.status === "done" && turnState.finalResult && turnState.activeTurnId) {
      const msgId = `assistant-${turnState.activeTurnId}`;
      setMessages((prev) => {
        if (prev.some((m) => m.id === msgId)) return prev;
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
          },
        ];
      });
    }
  }, [turnState.status, turnState.finalResult, turnState.activeTurnId]);

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

  // Handle pending actions from the brief card pills
  useEffect(() => {
    if (turnState.pendingAction) {
      handleSend(turnState.pendingAction);
      turnState.clearPendingAction();
    }
  }, [turnState.pendingAction, handleSend, turnState.clearPendingAction]);

  return (
    <main className="flex h-full flex-col overflow-hidden">
      <MessageList messages={messages} />

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
                      // Resend the last user message
                      const lastUserMsg = [...messages]
                        .reverse()
                        .find((m) => m.role === "user");
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
