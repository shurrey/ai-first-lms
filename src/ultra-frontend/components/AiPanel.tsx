"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { X, Sparkles, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ROLE_LABELS, useAuth } from "@/lib/auth-context";
import { useAiPanel } from "@/lib/ai-panel-context";
import { ApiError, apiFetch, apiJson } from "@/lib/api";
import { ApprovalCard, type ApprovalDecision, type PendingApproval } from "@/components/ApprovalCard";
import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";
import { parseAlignmentProposal, type AlignmentProposal } from "@/lib/alignment";

/** `generated` marks answers produced by a turn; `ran` lists the agents and tools that produced them. */
interface Message { role: "user" | "assistant"; content: string; generated?: boolean; ran?: string[]; }

const SPEAKER_LABEL = "Tutor (AI)";

export function AiPanel({ onClose, courseId, courseTitle }: { onClose: () => void; courseId: string; courseTitle: string }) {
  const { activeRole, ensureSession } = useAuth();
  const { queuedPrompts, takePrompt, markTurnCompleted, publishProposal } = useAiPanel();
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: `Ask a question about **${courseTitle}**. Answers are generated from the course materials.` },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  // Set synchronously so a re-run effect can't start a second turn before `loading` updates.
  const turnActiveRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const decideRef = useRef<((d: ApprovalDecision) => void) | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamText]);

  const sendMessage = useCallback(async (msg: string) => {
    turnActiveRef.current = true;
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setLoading(true);
    setStreamText("");

    try {
      const session = await ensureSession(courseId);
      const sid = session.sessionId;

      // Send message
      const converseRes = await apiFetch(`/api/converse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message: msg }),
      });
      const { turn_id, stream_url } = await converseRes.json();

      // Poll SSE stream for response
      let finalAnswer = "";
      let tokens = "";
      let ran: string[] = [];
      let proposals: AlignmentProposal[] = [];
      const maxWait = 90000;
      let start = Date.now();
      const decided = new Set<string>();

      while (Date.now() - start < maxWait) {
        const res = await apiFetch(stream_url);
        const text = await res.text();
        const lines = text.split("\n");
        // Each poll replays the turn's stream from the start.
        tokens = "";
        const ranSet = new Set<string>();
        let pending: PendingApproval | null = null;

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let event: { event?: string; payload?: Record<string, unknown> };
          try {
            event = JSON.parse(line.slice(6));
          } catch {
            console.warn("Skipping malformed SSE line", line);
            continue;
          }
          const payload = event.payload ?? {};
          if (event.event === "agent_start" && typeof payload.agent === "string") ranSet.add(`Agent: ${payload.agent}`);
          if (event.event === "agent_tool_call" && typeof payload.tool === "string") ranSet.add(`Tool: ${payload.tool}`);
          if (event.event === "agent_token" && payload.channel !== "thought" && typeof payload.delta === "string") {
            tokens += payload.delta;
          }
          if (event.event === "approval_request" && typeof payload.approval_id === "string") {
            pending = payload as unknown as PendingApproval;
          }
          if (event.event === "final") {
            finalAnswer = typeof payload.answer_markdown === "string" ? payload.answer_markdown : tokens;
            const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
            proposals = artifacts.flatMap((a) => parseAlignmentProposal(a) ?? []);
          }
        }
        ran = [...ranSet];
        setStreamText(tokens);

        if (finalAnswer) break;
        if (pending && !decided.has(pending.approval_id)) {
          // The turn is paused server-side until POST /api/approval; the wait for the person is not timed.
          const current = pending;
          setApproval(current);
          // A refused decision (422: an incomplete grade commit) leaves the approval pending
          // server-side, so the card stays up for another try.
          for (;;) {
            const decision = await new Promise<ApprovalDecision>((resolve) => { decideRef.current = resolve; });
            setApprovalBusy(true);
            try {
              await apiJson("/api/approval", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sid, turn_id, approval_id: current.approval_id, ...decision }),
              });
              break;
            } catch (err: unknown) {
              if (!(err instanceof ApiError) || err.status !== 422) throw err;
              setApprovalError(`Not accepted: ${err.message}`);
            } finally {
              setApprovalBusy(false);
            }
          }
          decided.add(current.approval_id);
          setApproval(null);
          setApprovalError(null);
          decideRef.current = null;
          inputRef.current?.focus();
          start = Date.now();
          continue;
        }
        await new Promise((r) => setTimeout(r, 800));
      }

      const answer = finalAnswer || tokens;
      proposals.forEach(publishProposal);
      setMessages((prev) => [
        ...prev,
        answer
          ? { role: "assistant", content: answer, generated: true, ran }
          : { role: "assistant", content: "No answer was generated. Please try again." },
      ]);
      setStreamText("");
    } catch (err: unknown) {
      console.error("AI panel turn failed", err);
      setMessages((prev) => [...prev, { role: "assistant", content: "Connection error. Please try again." }]);
    } finally {
      turnActiveRef.current = false;
      setLoading(false);
      markTurnCompleted();
    }
  }, [courseId, ensureSession, markTurnCompleted, publishProposal]);

  // Prompts that arrive while a turn runs (including one paused for approval) wait for it to end.
  const nextPrompt = queuedPrompts[0];
  useEffect(() => {
    if (!nextPrompt || loading || turnActiveRef.current) return;
    takePrompt();
    sendMessage(nextPrompt);
  }, [nextPrompt, queuedPrompts.length, loading, takePrompt, sendMessage]);

  const handleSend = useCallback(() => {
    if (!input.trim() || loading || turnActiveRef.current) return;
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
    <aside aria-label="AI assistant" className="fixed right-0 top-0 z-50 flex h-full w-[420px] flex-col border-l border-gray-200 bg-white shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#6366f1] text-white"><Sparkles className="h-4 w-4" /></div>
          <div>
            <h2 className="inline text-sm font-semibold">AI assistant</h2>
            <span className="ml-2 text-[10px] text-gray-600">{ROLE_LABELS[activeRole]}</span>
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close AI assistant" className="text-gray-500 hover:text-gray-700"><X aria-hidden="true" className="h-5 w-5" /></button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`rounded-lg px-3 py-2 text-sm ${msg.role === "user" ? "ml-8 bg-[#4f46e5] text-white" : "mr-4 border border-gray-200 bg-gray-50"}`}>
            {msg.role === "assistant" ? (
              <>
              <p className="mb-1 text-[10px] font-semibold text-gray-600">{SPEAKER_LABEL}</p>
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
              {msg.generated && <AiGeneratedLabel ran={msg.ran} />}
              </>
            ) : (
              <><span className="sr-only">You: </span>{msg.content}</>
            )}
          </div>
        ))}
        {streamText && (
          <div className="mr-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
            <p className="mb-1 text-[10px] font-semibold text-gray-600">{SPEAKER_LABEL}</p>
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamText}</ReactMarkdown>
            </div>
          </div>
        )}
        {approval && (
          <ApprovalCard approval={approval} busy={approvalBusy} error={approvalError} onDecide={(d) => decideRef.current?.(d)} />
        )}
        {loading && !streamText && !approval && (
          <div role="status" className="mr-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600 animate-pulse">
            Working…
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 p-3">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="Message the AI assistant"
            placeholder="Ask about this course..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400 leading-normal"
          />
          <button type="button" aria-label="Send message" onClick={handleSend} disabled={loading || !input.trim()} className="rounded-lg bg-[#6366f1] px-3 py-2 text-white hover:bg-[#4f46e5] disabled:opacity-50">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
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
