"use client";

import { useState, useCallback, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSession } from "@/lib/session-context";
import { converse } from "@/lib/api";
import { useEventStream } from "@/lib/use-event-stream";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import type { ChatMessage } from "./MessageBubble";

export function ChatPane() {
  const { sessionId } = useSession();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const turnState = useEventStream(sessionId, activeTurnId);

  // When the SSE stream produces a final result, add the assistant message
  useEffect(() => {
    if (turnState.status === "done" && turnState.finalResult) {
      setMessages((prev) => {
        // Replace the streaming placeholder with the final answer
        const withoutPlaceholder = prev.filter(
          (m) => m.id !== `streaming-${activeTurnId}`
        );
        return [
          ...withoutPlaceholder,
          {
            id: `assistant-${activeTurnId}`,
            role: "assistant" as const,
            content: turnState.finalResult!.answer_markdown,
            timestamp: new Date().toISOString(),
          },
        ];
      });
      setActiveTurnId(null);
    }
  }, [turnState.status, turnState.finalResult, activeTurnId]);

  // While streaming, show accumulated agent tokens as a live message
  useEffect(() => {
    if (turnState.status !== "streaming") return;
    const allTokens = Array.from(turnState.agentTokens.values()).join("");
    if (!allTokens) return;

    setMessages((prev) => {
      const idx = prev.findIndex(
        (m) => m.id === `streaming-${activeTurnId}`
      );
      const streamMsg: ChatMessage = {
        id: `streaming-${activeTurnId}`,
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
  }, [turnState.status, turnState.agentTokens, activeTurnId]);

  // Handle errors from the stream
  useEffect(() => {
    if (turnState.status === "error" && turnState.error) {
      setMessages((prev) => {
        const withoutPlaceholder = prev.filter(
          (m) => m.id !== `streaming-${activeTurnId}`
        );
        return [
          ...withoutPlaceholder,
          {
            id: `error-${activeTurnId}`,
            role: "assistant" as const,
            content: `Error: ${turnState.error!.message}`,
            timestamp: new Date().toISOString(),
          },
        ];
      });
      setActiveTurnId(null);
    }
  }, [turnState.status, turnState.error, activeTurnId]);

  const converseMutation = useMutation({
    mutationFn: (message: string) => {
      if (!sessionId) throw new Error("No active session");
      return converse(sessionId, message);
    },
    onSuccess: (data) => {
      setActiveTurnId(data.turn_id);
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
      <MessageList messages={messages} />
      <ChatInput
        onSend={handleSend}
        disabled={!sessionId}
        loading={converseMutation.isPending || turnState.status === "streaming"}
      />
    </main>
  );
}
