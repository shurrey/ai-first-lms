/**
 * Shared UI primitives and utilities used across CoursePanel role views.
 */

/**
 * Programmatically fills the chat textarea and submits the form.
 * Uses the native setter to work with React's controlled input pattern.
 */
export function sendPrompt(prompt: string): void {
  const input = document.querySelector<HTMLTextAreaElement>("form textarea");
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() =>
      requestAnimationFrame(() => form.requestSubmit()),
    );
  }
}

/** Uppercase micro-heading used to label panel sections. */
export function SectionLabel({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h3>
  );
}

/** Small clickable chip for quick-action prompts. */
export function Pill({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}): React.JSX.Element {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}

/** Label / value row for summary statistics. */
export function StatRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}): React.JSX.Element {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={valueClass ?? "font-medium"}>{value}</span>
    </div>
  );
}
