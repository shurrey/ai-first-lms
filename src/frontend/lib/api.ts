import type { Persona } from "./session-context";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function createSession(
  persona: Persona,
  courseId: string,
  personId?: string
): Promise<{ session_id: string }> {
  const res = await fetch(`${API_BASE}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      persona,
      course_id: courseId,
      ...(personId && { person_id: personId }),
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to create session: ${res.status}`);
  }
  return res.json();
}
