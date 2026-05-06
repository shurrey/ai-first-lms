"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidBlock } from "./MermaidBlock";
import { CodeSandbox } from "./CodeSandbox";
import { VisualBlock } from "./VisualBlock";
import { sendPrompt } from "@/components/CoursePanel/shared";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  followUps?: string[];
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

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
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ className, children, ...props }) {
                    const content = String(children).replace(/\n$/, "");
                    const langMatch = /language-(\S+)/.exec(className || "");
                    const lang = langMatch?.[1] || "";

                    // Mermaid diagrams
                    if (lang === "mermaid") {
                      return <MermaidBlock code={content} />;
                    }

                    // Interactive Python sandbox
                    if (lang === "python:interactive" || lang === "python:sandbox") {
                      return <CodeSandbox initialCode={content} />;
                    }

                    // Structured visual blocks (JSON)
                    if (lang.startsWith("visual:")) {
                      try {
                        const data = JSON.parse(content);
                        return <VisualBlock data={data} />;
                      } catch {
                        // Fall through to regular code block
                      }
                    }

                    // Regular code block (block vs inline detection)
                    const isBlock = content.includes("\n") || (className && className.includes("language-"));
                    if (isBlock) {
                      return (
                        <pre className="rounded-md bg-gray-950 p-3 overflow-x-auto">
                          <code className={className} {...props}>{content}</code>
                        </pre>
                      );
                    }

                    // Inline code
                    return <code className={className} {...props}>{children}</code>;
                  },
                  // Prevent wrapping code blocks in extra <pre>
                  pre({ children }) {
                    return <>{children}</>;
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
            {message.followUps && message.followUps.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-border/50 pt-2">
                {message.followUps.map((fu, i) => (
                  <button
                    key={i}
                    onClick={() => sendPrompt(fu)}
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
