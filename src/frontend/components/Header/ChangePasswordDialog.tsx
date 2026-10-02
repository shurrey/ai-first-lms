"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { changePassword, PASSWORD_MIN_LENGTH } from "@/lib/auth";

const fieldClass =
  "mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50";

export const PASSWORD_MESSAGES = {
  tooShort: `New password must be at least ${PASSWORD_MIN_LENGTH} characters.`,
  mismatch: "New passwords don't match.",
  wrongCurrent: "Current password is incorrect.",
  missingCurrent: "Enter your current password.",
  failed: "Couldn't change your password. Please try again.",
  success: "Password changed.",
} as const;

/** Native <dialog> via showModal(), which supplies the focus trap and Escape-to-close. */
export function ChangePasswordDialog({
  open,
  required,
  onClose,
}: {
  open: boolean;
  /** credentials.must_change: explain why the dialog opened on its own. */
  required: boolean;
  onClose: () => void;
}) {
  const { refresh } = useAuth();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const errorId = useId();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setCurrent("");
      setNext("");
      setConfirm("");
      setError(null);
      setDone(false);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    if (!current) return setError(PASSWORD_MESSAGES.missingCurrent);
    if (next.length < PASSWORD_MIN_LENGTH) return setError(PASSWORD_MESSAGES.tooShort);
    if (next !== confirm) return setError(PASSWORD_MESSAGES.mismatch);

    setError(null);
    setSubmitting(true);
    try {
      await changePassword(current, next);
      setDone(true);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) setError(PASSWORD_MESSAGES.wrongCurrent);
      else if (err instanceof ApiError && err.status === 422) setError(PASSWORD_MESSAGES.tooShort);
      else setError(PASSWORD_MESSAGES.failed);
    } finally {
      setSubmitting(false);
    }
  }

  const invalid = error !== null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onClose={onClose}
      className="m-auto w-full max-w-sm rounded-xl border border-border bg-card p-6 text-card-foreground shadow-lg backdrop:bg-black/40"
    >
      <h2 id={titleId} className="text-base font-semibold">
        Change password
      </h2>
      {required && !done && (
        <p className="mt-1 text-sm text-muted-foreground">
          You need to set a new password before continuing.
        </p>
      )}

      {done ? (
        <div className="mt-4 space-y-4">
          <p role="status" className="text-sm">
            {PASSWORD_MESSAGES.success}
          </p>
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Close
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-3">
          <div id={errorId} role="alert" className="text-sm font-medium text-destructive">
            {error}
          </div>
          <div>
            <label htmlFor="current-password" className="block text-sm font-medium">
              Current password
            </label>
            <input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              aria-invalid={invalid}
              aria-describedby={invalid ? errorId : undefined}
              className={fieldClass}
            />
          </div>
          <div>
            <label htmlFor="new-password" className="block text-sm font-medium">
              New password
            </label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              value={next}
              onChange={(e) => setNext(e.target.value)}
              aria-invalid={invalid}
              aria-describedby={`${titleId}-hint${invalid ? ` ${errorId}` : ""}`}
              className={fieldClass}
            />
            <p id={`${titleId}-hint`} className="mt-1 text-xs text-muted-foreground">
              At least {PASSWORD_MIN_LENGTH} characters.
            </p>
          </div>
          <div>
            <label htmlFor="confirm-password" className="block text-sm font-medium">
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-invalid={invalid}
              aria-describedby={invalid ? errorId : undefined}
              className={fieldClass}
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => dialogRef.current?.close()}
              className="rounded-md border border-input px-3 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Cancel
            </button>
            <button
              type="submit"
              aria-disabled={submitting}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-disabled:opacity-70"
            >
              {submitting ? "Saving…" : "Change password"}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
