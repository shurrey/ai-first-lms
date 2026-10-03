"use client";

import { useEffect, useState } from "react";
import { ApiError, apiJson } from "./api";
import { feedbackStillOpen, pollDelay } from "./assessment";
import type { SubmissionFeedback } from "./types";

export type FeedbackLoad =
  | { status: "idle" | "loading" }
  | { status: "ready"; feedback: SubmissionFeedback }
  | { status: "error"; message: string };

/**
 * GET /api/feedback/{id}, re-polled with backoff while it is pending or awaiting release.
 * Feedback released outside a turn is not pushed (events.md), so polling is the delivery path.
 * Changing `restart` (after a retry) starts polling again.
 */
export function useFeedbackPoll(submissionId: string | null, restart = 0): FeedbackLoad {
  // Tagged with the id it was loaded for, so a new id never shows the previous submission's feedback.
  const [loaded, setLoaded] = useState<{ id: string; state: FeedbackLoad } | null>(null);

  useEffect(() => {
    if (!submissionId) return;
    const setState = (state: FeedbackLoad) => setLoaded({ id: submissionId, state });
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    setState({ status: "loading" });

    const poll = () => {
      apiJson<SubmissionFeedback>(`/api/feedback/${encodeURIComponent(submissionId)}`, { reportForbidden: false })
        .then((feedback) => {
          if (cancelled) return;
          setState({ status: "ready", feedback });
          if (feedbackStillOpen(feedback.status)) timer = setTimeout(poll, pollDelay(attempt++));
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          if (err instanceof ApiError && err.status === 401) return;
          const message = err instanceof ApiError && (err.status === 403 || err.status === 404)
            ? "This feedback isn't available to your role."
            : err instanceof Error ? err.message : String(err);
          setState({ status: "error", message });
        });
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [submissionId, restart]);

  if (!submissionId) return { status: "idle" };
  if (!loaded || loaded.id !== submissionId) return { status: "loading" };
  return loaded.state;
}

/** POST /api/feedback/{id}/retry; resolves to an error message, or null when a new run started. */
export async function retryFeedback(submissionId: string): Promise<string | null> {
  try {
    await apiJson<SubmissionFeedback>(`/api/feedback/${encodeURIComponent(submissionId)}/retry`, {
      method: "POST",
      reportForbidden: false,
    });
    return null;
  } catch (err: unknown) {
    if (err instanceof ApiError && err.status === 403) return "Your role can't retry feedback here.";
    if (err instanceof ApiError && err.status === 409) return "This feedback is no longer marked as failed. Reload to see it.";
    return err instanceof Error ? err.message : String(err);
  }
}
