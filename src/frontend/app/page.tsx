"use client";

import { ContextPane } from "@/components/ContextPane/ContextPane";
import { ChatPane } from "@/components/ChatPane/ChatPane";
import { ActivityPane } from "@/components/ActivityPane/ActivityPane";
import { TurnProvider } from "@/lib/turn-context";

export default function Home() {
  return (
    <TurnProvider>
      <div className="flex h-full flex-col">
        <header className="flex h-12 shrink-0 items-center border-b border-border bg-background px-4">
          <h1 className="text-sm font-semibold tracking-tight">
            AI-First LMS
          </h1>
        </header>
        <div className="grid flex-1 grid-cols-[280px_1fr_320px] overflow-hidden">
          <ContextPane />
          <ChatPane />
          <ActivityPane />
        </div>
      </div>
    </TurnProvider>
  );
}
