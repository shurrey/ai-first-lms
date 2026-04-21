"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  followUps?: string[];
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  const handleFollowUp = (prompt: string) => {
    const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
    const form = input?.closest("form");
    if (input && form) {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      nativeSetter?.call(input, prompt);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
    }
  };

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground"
        }`}
      >
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
            {message.followUps && message.followUps.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-border/50 pt-2">
                {message.followUps.map((fu, i) => (
                  <button
                    key={i}
                    onClick={() => handleFollowUp(fu)}
                    className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-primary/10 transition-colors"
                  >
                    {fu}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
