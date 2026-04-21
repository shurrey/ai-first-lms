"use client";

import { Header } from "@/components/Header/Header";
import { ChatPane } from "@/components/ChatPane/ChatPane";
import { CoursePanel } from "@/components/CoursePanel/CoursePanel";
import { TurnProvider } from "@/lib/turn-context";

export default function Home() {
  return (
    <TurnProvider>
      <div className="flex h-full flex-col">
        <Header />
        <div className="grid flex-1 grid-cols-[1fr_300px] overflow-hidden">
          <ChatPane />
          <CoursePanel />
        </div>
      </div>
    </TurnProvider>
  );
}
