/** Shown when the API answers 403 for something the user tried to open. */
export function AccessDenied({ what }: { what?: string }) {
  return (
    <div role="alert" className="rounded-lg border border-border bg-card p-3 text-xs">
      <p className="font-medium">You don&apos;t have access to this.</p>
      {what && <p className="mt-1 text-muted-foreground">{what}</p>}
    </div>
  );
}
