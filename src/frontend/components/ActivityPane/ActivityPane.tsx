export function ActivityPane() {
  return (
    <aside className="flex h-full flex-col border-l border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
        Activity
      </h2>
      <div className="flex-1 space-y-2">
        <p className="text-xs text-muted-foreground">
          Agent activity and results will appear here.
        </p>
      </div>
    </aside>
  );
}
