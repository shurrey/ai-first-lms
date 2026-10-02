"use client";

export type ArtifactStatus =
  | "generated"
  | "draft"
  | "awaiting_approval"
  | "approved"
  | "rejected";

interface CanvasShellProps {
  title: string;
  status: ArtifactStatus;
  children: React.ReactNode;
}

const STATUS_BADGE: Record<ArtifactStatus, { label: string; className: string }> = {
  generated: { label: "Generated", className: "bg-muted text-foreground" },
  draft: { label: "Draft", className: "bg-muted text-foreground" },
  awaiting_approval: {
    label: "Awaiting Approval",
    className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  },
  approved: {
    label: "Approved",
    className: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  },
  rejected: {
    label: "Rejected",
    className: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  },
};

export function CanvasShell({ title, status, children }: CanvasShellProps) {
  const badge = STATUS_BADGE[status];

  return (
    <div className="rounded-lg border border-border bg-card" data-testid="canvas-shell">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}
        >
          {badge.label}
        </span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
