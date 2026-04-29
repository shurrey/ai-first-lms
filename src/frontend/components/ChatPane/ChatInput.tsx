"use client";

import { useState, useCallback, useRef, type FormEvent, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
  loading: boolean;
}

export function ChatInput({ onSend, disabled, loading }: ChatInputProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault();
      const trimmed = text.trim();
      if (!trimmed || disabled || loading) return;
      onSend(trimmed);
      setText("");
      // Reset height
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    },
    [text, disabled, loading, onSend]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 150)}px`;
  }, []);

  return (
    <form
      onSubmit={handleSubmit}
      className="shrink-0 border-t border-border p-4"
    >
      <div className="mx-auto flex max-w-2xl gap-2 items-end">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => { setText(e.target.value); handleInput(); }}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled ? "Select a course to start..." : "Type a message... (Shift+Enter for new line)"
          }
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/50 disabled:opacity-50 leading-normal"
        />
        <Button type="submit" disabled={disabled || loading || !text.trim()}>
          {loading ? "..." : "Send"}
        </Button>
      </div>
    </form>
  );
}
