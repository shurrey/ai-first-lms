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

export async function converse(
  sessionId: string,
  message: string
): Promise<{ turn_id: string; stream_url: string }> {
  const res = await fetch(`${API_BASE}/api/converse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to send message: ${res.status}`);
  }
  return res.json();
}

export type ApprovalDecision = "approve" | "edit" | "reject";

export async function submitApproval(params: {
  sessionId: string;
  turnId: string;
  approvalId: string;
  decision: ApprovalDecision;
  editedPayload?: Record<string, unknown>;
  note?: string;
}): Promise<void> {
  const res = await fetch(`${API_BASE}/api/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: params.sessionId,
      turn_id: params.turnId,
      approval_id: params.approvalId,
      decision: params.decision,
      ...(params.editedPayload && { edited_payload: params.editedPayload }),
      ...(params.note && { note: params.note }),
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to submit approval: ${res.status}`);
  }
}

export async function submitClarification(params: {
  sessionId: string;
  turnId: string;
  answer: string;
}): Promise<void> {
  const res = await fetch(`${API_BASE}/api/clarify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: params.sessionId,
      turn_id: params.turnId,
      answer: params.answer,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to submit clarification: ${res.status}`);
  }
}
