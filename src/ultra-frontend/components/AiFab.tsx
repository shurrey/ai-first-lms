"use client";
import { Sparkles } from "lucide-react";

export function AiFab({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Open AI assistant"
      onClick={onClick}
      className="fixed bottom-6 right-6 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-[#6366f1] text-white shadow-lg shadow-indigo-500/30 hover:bg-[#4f46e5] transition-colors"
    >
      <Sparkles aria-hidden="true" className="h-5 w-5" />
    </button>
  );
}
