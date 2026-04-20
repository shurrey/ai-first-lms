export function ContextPane() {
  return (
    <nav className="flex h-full flex-col overflow-y-auto border-r border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Context
      </h2>
      <div className="flex-1 space-y-4">
        <div className="rounded-lg border border-border bg-card p-3">
          <p className="text-xs text-muted-foreground">Persona</p>
          <p className="text-sm font-medium">Student</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-3">
          <p className="text-xs text-muted-foreground">Course</p>
          <p className="text-sm font-medium">Select a course...</p>
        </div>
      </div>
    </nav>
  );
}
