"use client";

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSession } from "@/lib/session-context";
import { converse } from "@/lib/api";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import type { ChatMessage } from "./MessageBubble";

export function ChatPane() {
  const { sessionId } = useSession();
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const converseMutation = useMutation({
    mutationFn: (message: string) => {
      if (!sessionId) throw new Error("No active session");
      return converse(sessionId, message);
    },
    onSuccess: () => {
      // The turn_id is returned; actual assistant response comes via SSE (T-F-005).
      // For now, add a placeholder assistant message.
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: "_Waiting for response via SSE stream..._",
          timestamp: new Date().toISOString(),
        },
      ]);
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
        loading={converseMutation.isPending}
      />
    </main>
  );
}
