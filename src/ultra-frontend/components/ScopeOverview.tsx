"use client";

import { Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export function ScopeOverview({ title, onAsk }: { title: string; onAsk: (prompt?: string) => void }) {
  const { activeRole, me } = useAuth();
  const prompt =
    activeRole === "advisor"
      ? "Which of my assigned students need attention this week, and why?"
      : "Summarize learner progress across the institution this term.";

  return (
    <div className="max-w-2xl p-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-gray-700">
        {activeRole === "advisor"
          ? `This view covers the ${me.advisees_count} students assigned to you, across every course they take.`
          : "This view covers every course and learner in the institution."}{" "}
        Use the assistant to ask questions across this scope.
      </p>
      <button
        type="button"
        onClick={() => onAsk(prompt)}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[#4f46e5] px-4 py-2 text-sm font-medium text-white hover:bg-[#4338ca] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f46e5]"
      >
        <Sparkles aria-hidden="true" className="h-4 w-4" />
        {prompt}
      </button>
    </div>
  );
}
