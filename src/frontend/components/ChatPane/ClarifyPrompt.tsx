"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { submitClarification } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import type { ClarifyPayload } from "@/lib/events";

interface ClarifyPromptProps {
  clarify: ClarifyPayload;
}

export function ClarifyPrompt({ clarify }: ClarifyPromptProps) {
  const { sessionId } = useSession();
  const { activeTurnId } = useTurn();
  const [answer, setAnswer] = useState("");

  const mutation = useMutation({
    mutationFn: (text: string) => {
      if (!sessionId || !activeTurnId) {
        throw new Error("No active session/turn");
      }
      return submitClarification({
        sessionId,
        turnId: activeTurnId,
        answer: text,
      });
    },
  });

  const handleSubmit = (text: string) => {
    if (!text.trim()) return;
    mutation.mutate(text.trim());
  };

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800 dark:bg-blue-950">
      <p className="text-sm font-medium">{clarify.question}</p>
      <p className="mt-1 text-xs text-muted-foreground">{clarify.reason}</p>

      {clarify.options && clarify.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {clarify.options.map((opt, i) => (
            <Button
              key={i}
              size="sm"
              variant="outline"
              disabled={mutation.isPending || mutation.isSuccess}
              onClick={() => handleSubmit(opt)}
            >
              {opt}
            </Button>
          ))}
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <input
          type="text"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmit(answer);
          }}
          placeholder="Type your answer..."
          disabled={mutation.isPending || mutation.isSuccess}
          className="flex-1 rounded border border-input bg-background px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-50"
        />
        <Button
          size="sm"
          onClick={() => handleSubmit(answer)}
          disabled={mutation.isPending || mutation.isSuccess || !answer.trim()}
        >
          Answer
        </Button>
      </div>

      {mutation.isSuccess && (
        <p className="mt-1 text-xs text-green-600">Answer submitted</p>
      )}
    </div>
  );
}
