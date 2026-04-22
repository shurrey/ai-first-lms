export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

import type { Persona, PageData } from "./types";

export async function createPageSession(
  persona: Persona,
  courseId: string,
  page: string,
): Promise<{ session_id: string; brief_turn_id: string; stream_url: string }> {
  const res = await fetch(`${API_BASE}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ persona, course_id: courseId, page }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function fetchPageData<T>(
  persona: Persona,
  courseId: string,
  page: string,
): Promise<T> {
  const session = await createPageSession(persona, courseId, page);

  // Poll the stream for the page_data event
  const streamUrl = `${API_BASE}${session.stream_url}`;
  const maxWait = 30000;
  const start = Date.now();

  while (Date.now() - start < maxWait) {
    const res = await fetch(streamUrl);
    const text = await res.text();

    // Parse SSE events
    const lines = text.split("\n");
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const event = JSON.parse(line.slice(6));
          if (event.event === "page_data") {
            return event.payload.data as T;
          }
        } catch { /* skip unparseable lines */ }
      }
    }

    // Wait a bit before retrying
    await new Promise((r) => setTimeout(r, 500));
  }

  throw new Error(`Timeout waiting for page data: ${page}`);
}
