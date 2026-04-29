"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { X, Sparkles, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { usePersona } from "@/lib/persona-context";
import { useAiPanel } from "@/lib/ai-panel-context";
import { API_BASE } from "@/lib/api";

interface Message { role: "user" | "assistant"; content: string; }

export function AiPanel({ onClose, courseId, courseTitle }: { onClose: () => void; courseId: string; courseTitle: string }) {
  const { persona, ensureSession } = usePersona();
  const { initialPrompt, clearPrompt } = useAiPanel();
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: `Hi! I'm your AI assistant for **${courseTitle}**. How can I help?` },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef(false);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamText]);

  // Auto-send initial prompt when panel opens with one
  useEffect(() => {
    if (initialPrompt && !autoSentRef.current && !loading) {
      autoSentRef.current = true;
      clearPrompt();
      sendMessage(initialPrompt);
    }
  }, [initialPrompt, loading]);

  const sendMessage = useCallback(async (msg: string) => {
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setLoading(true);
    setStreamText("");

    try {
      const session = await ensureSession(courseId);
      const sid = session.sessionId;

      // Send message
      const converseRes = await fetch(`${API_BASE}/api/converse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message: msg }),
      });
      const { turn_id, stream_url } = await converseRes.json();

      // Poll SSE stream for response
      let finalAnswer = "";
      let tokens = "";
      const maxWait = 90000;
      const start = Date.now();

      while (Date.now() - start < maxWait) {
        const res = await fetch(`${API_BASE}${stream_url}`);
        const text = await res.text();
        const lines = text.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.event === "agent_token") {
              tokens += event.payload?.token ?? "";
              setStreamText(tokens);
            }
            if (event.event === "final") {
              finalAnswer = event.payload?.answer_markdown ?? tokens;
            }
          } catch { /* skip */ }
        }

        if (finalAnswer) break;
        await new Promise((r) => setTimeout(r, 800));
      }

      const answer = finalAnswer || tokens || "I wasn't able to generate a response. Please try again.";
      setMessages((prev) => [...prev, { role: "assistant", content: answer }]);
      setStreamText("");
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "Connection error. Please try again." }]);
    } finally {
      setLoading(false);
    }
  }, [courseId, ensureSession]);

  const handleSend = useCallback(() => {
    if (!input.trim() || loading) return;
    const msg = input.trim();
    setInput("");
    sendMessage(msg);
  }, [input, loading, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="fixed right-0 top-0 z-50 flex h-full w-[420px] flex-col border-l border-gray-200 bg-white shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#6366f1] text-white"><Sparkles className="h-4 w-4" /></div>
          <div>
            <span className="text-sm font-semibold">AI Assistant</span>
            <span className="ml-2 text-[10px] text-gray-400">{persona}</span>
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`rounded-lg px-3 py-2 text-sm ${msg.role === "user" ? "ml-8 bg-[#6366f1] text-white" : "mr-4 border border-gray-200 bg-gray-50"}`}>
            {msg.role === "assistant" ? (
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code({ className, children }) {
                      const content = String(children).replace(/\n$/, "");
                      const lang = /language-(\S+)/.exec(className || "")?.[1] || "";
                      if (lang === "mermaid") {
                        return <MermaidInline code={content} />;
                      }
                      if (lang === "python:interactive" || lang === "python:sandbox") {
                        return <CodeSandboxInline code={content} />;
                      }
                      const isBlock = content.includes("\n");
                      if (isBlock) {
                        return <pre className="rounded bg-gray-900 p-2 overflow-x-auto text-xs"><code className={className}>{content}</code></pre>;
                      }
                      return <code className={className}>{children}</code>;
                    },
                    pre({ children }) { return <>{children}</>; },
                  }}
                >{msg.content}</ReactMarkdown>
              </div>
            ) : msg.content}
          </div>
        ))}
        {streamText && (
          <div className="mr-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamText}</ReactMarkdown>
            </div>
          </div>
        )}
        {loading && !streamText && (
          <div className="mr-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-400 animate-pulse">
            Thinking...
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 p-3">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about this course..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400 leading-normal"
          />
          <button onClick={handleSend} disabled={loading || !input.trim()} className="rounded-lg bg-[#6366f1] px-3 py-2 text-white hover:bg-[#4f46e5] disabled:opacity-50">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/** Inline Mermaid renderer for AI panel */
function MermaidInline({ code }: { code: string }) {
  const [svg, setSvg] = useState("");
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });
        const id = `m-${Math.random().toString(36).slice(2, 7)}`;
        const { svg: rendered } = await mermaid.render(id, code.trim());
        if (!cancelled) setSvg(rendered);
      } catch { /* ignore render errors */ }
    })();
    return () => { cancelled = true; };
  }, [code]);
  if (!svg) return <pre className="text-xs bg-gray-100 p-2 rounded">{code}</pre>;
  return <div className="my-2 flex justify-center bg-white rounded border p-2" dangerouslySetInnerHTML={{ __html: svg }} />;
}

/** Inline code sandbox for AI panel */
function CodeSandboxInline({ code }: { code: string }) {
  const [value, setValue] = useState(code.trim());
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const pyRef = useRef<any>(null);

  const run = async () => {
    setRunning(true);
    setOutput("");
    try {
      if (!pyRef.current) {
        if (!(window as any).loadPyodide) {
          await new Promise<void>((res, rej) => {
            const s = document.createElement("script");
            s.src = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
            s.onload = () => res();
            s.onerror = () => rej();
            document.head.appendChild(s);
          });
        }
        pyRef.current = await (window as any).loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/" });
      }
      const py = pyRef.current;
      py.runPython("import sys; from io import StringIO; sys.stdout=StringIO(); sys.stderr=StringIO()");
      try {
        py.runPython(value);
        setOutput(py.runPython("sys.stdout.getvalue()") + py.runPython("sys.stderr.getvalue()"));
      } catch (e: any) { setOutput(py.runPython("sys.stderr.getvalue()") || String(e)); }
    } catch (e) { setOutput(String(e)); }
    setRunning(false);
  };

  return (
    <div className="my-2 rounded border border-indigo-200 overflow-hidden text-xs">
      <div className="flex justify-between bg-indigo-50 px-2 py-1 border-b border-indigo-200">
        <span className="text-indigo-600 font-medium">Python</span>
        <button onClick={run} disabled={running} className="bg-indigo-500 text-white px-2 py-0.5 rounded text-[10px] disabled:opacity-50">
          {running ? "Running..." : "Run"}
        </button>
      </div>
      <textarea value={value} onChange={(e) => setValue(e.target.value)} className="w-full bg-gray-950 text-green-300 font-mono p-2 outline-none resize-none" rows={Math.max(value.split("\n").length, 3)} spellCheck={false} />
      {output && <pre className="bg-gray-900 text-gray-200 p-2 border-t border-indigo-200 font-mono whitespace-pre-wrap">{output}</pre>}
    </div>
  );
}
