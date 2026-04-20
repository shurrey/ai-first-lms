"use client";

import { ActivityTree } from "./ActivityTree";
import { CanvasRouter } from "@/components/Canvas/CanvasRouter";
import { useTurn } from "@/lib/turn-context";

export function ActivityPane() {
  const turn = useTurn();
  const artifacts = turn.finalResult?.artifacts ?? [];

  return (
    <aside className="flex h-full flex-col overflow-y-auto border-l border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Activity
      </h2>
      <div className="flex-1 space-y-4">
        <ActivityTree />
        {artifacts.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Artifacts
            </h3>
            {artifacts.map((artifact) => (
              <CanvasRouter
                key={artifact.artifact_id}
                artifact={artifact}
                status="draft"
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
