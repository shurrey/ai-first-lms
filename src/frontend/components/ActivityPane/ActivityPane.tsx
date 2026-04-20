"use client";

import { ActivityTree } from "./ActivityTree";

export function ActivityPane() {
  return (
    <aside className="flex h-full flex-col overflow-y-auto border-l border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Activity
      </h2>
      <div className="flex-1">
        <ActivityTree />
      </div>
    </aside>
  );
}
