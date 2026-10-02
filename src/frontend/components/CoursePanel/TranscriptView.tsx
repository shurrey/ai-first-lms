"use client";

import { useState } from "react";
import { useApiGet } from "@/lib/use-api";
import { AccessDenied } from "@/components/common/AccessDenied";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface TranscriptTurn {
  role: string;
  content: string;
  created_at: string;
}

interface TranscriptData {
  session_id: string;
  student_name: string;
  course_title: string;
  created_at: string;
  turns: TranscriptTurn[];
}

export function TranscriptView({
  sessionId,
  onBack,
}: {
  sessionId: string;
  onBack: () => void;
}) {
  const transcript = useApiGet<TranscriptData>(`/api/transcript/${encodeURIComponent(sessionId)}`);
  const data = transcript.data ?? null;
  const [modalOpen, setModalOpen] = useState(false);

  if (transcript.forbidden) {
    return (
      <div className="space-y-3">
        <button
          onClick={onBack}
          className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        >
          &larr; Back to sessions
        </button>
        <AccessDenied />
      </div>
    );
  }

  if (transcript.loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading transcript...</p>;
  }

  if (!data || !data.turns || data.turns.length === 0) {
    return (
      <div className="space-y-3">
        <button
          onClick={onBack}
          className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        >
          &larr; Back to sessions
        </button>
        <p className="text-xs text-muted-foreground">No conversation in this session.</p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button
            onClick={onBack}
            className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            &larr; Back to sessions
          </button>
          <button
            onClick={() => setModalOpen(true)}
            className="rounded-md border border-border bg-background px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title="Expand transcript"
          >
            Expand
          </button>
        </div>

        <TranscriptHeader data={data} />
        <TranscriptMessages data={data} />
      </div>

      {/* Modal overlay */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
          onClick={() => setModalOpen(false)}
        >
          <div
            className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <div>
                <div className="text-sm font-semibold">{data.student_name}</div>
                <div className="text-xs text-muted-foreground">
                  {data.course_title} &middot; {formatDate(data.created_at)} &middot; {data.turns.length} messages
                </div>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="rounded-md border border-border px-3 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              >
                Close
              </button>
            </div>

            {/* Modal body — scrollable transcript */}
            <div className="flex-1 overflow-y-auto p-6">
              <div className="mx-auto max-w-2xl space-y-4">
                {data.turns.map((turn, i) => (
                  <div
                    key={i}
                    className={`rounded-lg p-4 ${
                      turn.role === "user"
                        ? "bg-primary/10 border border-primary/20"
                        : "bg-muted border border-border"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-muted-foreground">
                        {turn.role === "user" ? data.student_name : "Tutor (AI)"}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {formatTime(turn.created_at)}
                      </span>
                    </div>
                    {turn.role === "user" ? (
                      <p className="text-sm">{turn.content}</p>
                    ) : (
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {turn.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** Compact header shown in the side panel */
function TranscriptHeader({ data }: { data: TranscriptData }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs font-medium">{data.student_name}</div>
      <div className="text-[10px] text-muted-foreground">{data.course_title}</div>
      <div className="text-[10px] text-muted-foreground">
        {formatDate(data.created_at)} &middot; {data.turns.length} messages
      </div>
    </div>
  );
}

/** Message list — used in both panel and modal */
function TranscriptMessages({ data }: { data: TranscriptData }) {
  return (
    <div className="space-y-2">
      {data.turns.map((turn, i) => (
        <div
          key={i}
          className={`rounded-lg p-2.5 text-xs ${
            turn.role === "user"
              ? "bg-primary/10 border border-primary/20"
              : "bg-muted border border-border"
          }`}
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-semibold uppercase text-muted-foreground">
              {turn.role === "user" ? data.student_name : "Tutor (AI)"}
            </span>
            <span className="text-[9px] text-muted-foreground">
              {formatTime(turn.created_at)}
            </span>
          </div>
          {turn.role === "user" ? (
            <p>{turn.content}</p>
          ) : (
            <div className="prose prose-xs max-w-none dark:prose-invert [&_p]:text-xs [&_li]:text-xs [&_h3]:text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {turn.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
