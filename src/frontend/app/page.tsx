import { ContextPane } from "@/components/ContextPane/ContextPane";
import { ChatPane } from "@/components/ChatPane/ChatPane";
import { ActivityPane } from "@/components/ActivityPane/ActivityPane";

export default function Home() {
  return (
    <div className="grid h-full grid-cols-[280px_1fr_320px]">
      <ContextPane />
      <ChatPane />
      <ActivityPane />
    </div>
  );
}
