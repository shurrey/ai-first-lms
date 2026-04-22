"use client";
import { useState } from "react";
import { X, Sparkles, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message { role: "user" | "assistant"; content: string; }

export function AiPanel({ onClose, courseTitle }: { onClose: () => void; courseTitle: string }) {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: `Hi! I'm your AI assistant for **${courseTitle}**. How can I help?` },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);
    setTimeout(() => {
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: "I'm connected to the same AI orchestrator that powers the chat-first UI. I can help you grade papers, identify at-risk students, generate quizzes, and more. Full integration coming soon!"
      }]);
      setLoading(false);
    }, 1000);
  };

  return (
    <div className="fixed right-0 top-0 z-50 flex h-full w-[380px] flex-col border-l border-gray-200 bg-white shadow-2xl">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#6366f1] text-white"><Sparkles className="h-4 w-4" /></div>
          <span className="text-sm font-semibold">AI Assistant</span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`rounded-lg px-3 py-2 text-sm ${msg.role === "user" ? "ml-8 bg-[#6366f1] text-white" : "mr-8 border border-gray-200 bg-gray-50"}`}>
            {msg.role === "assistant" ? (
              <div className="prose prose-sm max-w-none"><ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown></div>
            ) : msg.content}
          </div>
        ))}
        {loading && <div className="mr-8 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-400">Thinking...</div>}
      </div>
      <div className="border-t border-gray-200 p-3">
        <div className="flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Ask about this course..." className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
          <button onClick={handleSend} disabled={loading || !input.trim()} className="rounded-lg bg-[#6366f1] px-3 py-2 text-white hover:bg-[#4f46e5] disabled:opacity-50">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
