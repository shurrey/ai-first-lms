"use client";

import { Button } from "@/components/ui/button";
import type { ErrorPayload } from "@/lib/events";

const ERROR_LABELS: Record<string, string> = {
  budget_exceeded: "Budget limit reached",
  permission_denied: "Permission denied",
  agent_failure: "Agent encountered an error",
  mcp_failure: "Data service error",
  llm_failure: "AI model error",
  timeout: "Request timed out",
  internal: "Internal error",
};

interface ErrorDisplayProps {
  error: ErrorPayload;
  onRetry?: () => void;
}

export function ErrorDisplay({ error, onRetry }: ErrorDisplayProps) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950">
      <p className="text-sm font-medium text-red-800 dark:text-red-200">
        {ERROR_LABELS[error.code] ?? "Error"}
      </p>
      <p className="mt-1 text-xs text-red-600 dark:text-red-300">
        {error.message}
      </p>
      {error.retriable && onRetry && (
        <Button
          size="sm"
          variant="outline"
          onClick={onRetry}
          className="mt-2"
        >
          Retry
        </Button>
      )}
    </div>
  );
}
