"use client";

import { useEffect, useRef, useState } from "react";
import { BarChart3 } from "lucide-react";
import { MeasurementCanvas } from "@/components/Canvas/MeasurementCanvas";
import type { PersonRole } from "@/lib/auth";

/** CoursePanel entry point to the MeasurementCanvas, shown in a native modal <dialog>. */
export function AiReviewButton({ courseId, role }: { courseId: string | null; role: PersonRole }) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mb-3 inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <BarChart3 aria-hidden="true" className="h-3.5 w-3.5" />
        Open AI Review
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby="ai-review-title"
        onClose={() => setOpen(false)}
        className="m-auto max-h-[90vh] w-[min(960px,95vw)] overflow-y-auto rounded-lg border border-border bg-background p-6 text-foreground shadow-xl backdrop:bg-black/40"
      >
        <div className="mb-2 flex justify-end">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-md border border-input px-3 py-1 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Close
          </button>
        </div>
        {open && <MeasurementCanvas courseId={courseId} role={role} />}
      </dialog>
    </>
  );
}
