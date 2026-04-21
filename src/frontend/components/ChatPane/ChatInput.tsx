"use client";

import { useState, useCallback, type FormEvent } from "react";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
  loading: boolean;
  prefill?: string | null;
  onPrefillConsumed?: () => void;
}

export function ChatInput({ onSend, disabled, loading, prefill, onPrefillConsumed }: ChatInputProps) {
  const [text, setText] = useState("");

  // Pre-fill text from brief card action buttons
  if (prefill && prefill !== text) {
    setText(prefill);
    onPrefillConsumed?.();
  }

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmed = text.trim();
      if (!trimmed || disabled || loading) return;
      onSend(trimmed);
      setText("");
    },
    [text, disabled, loading, onSend]
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="shrink-0 border-t border-border p-4"
    >
      <div className="mx-auto flex max-w-2xl gap-2">
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            disabled ? "Select a course to start..." : "Type a message..."
          }
          disabled={disabled}
          className="flex-1 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/50 disabled:opacity-50"
        />
        <Button type="submit" disabled={disabled || loading || !text.trim()}>
          {loading ? "..." : "Send"}
        </Button>
      </div>
    </form>
  );
}
