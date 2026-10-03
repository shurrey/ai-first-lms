"use client";

import { useEffect, useRef } from "react";

/** Native modal <dialog> for a REST-driven canvas; Escape and Close both call `onClose`. */
export function CanvasDialog({
  open,
  onClose,
  label,
  children,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      onClose={onClose}
      className="m-auto max-h-[90vh] w-[min(960px,95vw)] overflow-y-auto rounded-lg border border-border bg-background p-6 text-foreground shadow-xl backdrop:bg-black/40"
    >
      <div className="mb-2 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="min-h-6 rounded-md border border-input px-3 py-1 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          Close
        </button>
      </div>
      {open && children}
    </dialog>
  );
}
