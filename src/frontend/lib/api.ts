import { redirectToLogin } from "./navigation";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const CSRF_COOKIE = "lms_csrf";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** Thrown for any non-2xx response that the caller has to handle (401 never reaches callers). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export interface ApiFetchOptions extends RequestInit {
  /** Return a 401 to the caller instead of redirecting to /login (used by the login form). */
  allowUnauthorized?: boolean;
}

/**
 * fetch against the orchestrator with the session cookie, plus X-CSRF-Token on
 * non-GET requests. A 401 clears in-memory state by navigating to /login?next=…,
 * so the returned promise never settles in that case.
 */
export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {}
): Promise<Response> {
  const { allowUnauthorized, headers: initHeaders, ...init } = options;
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(initHeaders);
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });

  if (res.status === 401 && !allowUnauthorized) {
    redirectToLogin();
    return new Promise<Response>(() => {});
  }
  return res;
}

async function errorDetail(res: Response): Promise<unknown> {
  try {
    return (await res.json())?.detail;
  } catch {
    return undefined;
  }
}

/** apiFetch + JSON body + JSON result; non-2xx becomes ApiError. */
export async function apiJson<T>(
  path: string,
  options: ApiFetchOptions & { json?: unknown } = {}
): Promise<T> {
  const { json, headers, ...rest } = options;
  const h = new Headers(headers);
  if (json !== undefined) h.set("Content-Type", "application/json");
  const res = await apiFetch(path, {
    ...rest,
    headers: h,
    ...(json !== undefined && { body: JSON.stringify(json) }),
  });
  if (!res.ok) {
    const detail = await errorDetail(res);
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : `Request failed: ${res.status}`,
      detail
    );
  }
  // 202/204 acknowledgements may have an empty body.
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export interface CreateSessionResult {
  session_id: string;
  person_id: string | null;
  course_uuid: string | null;
  brief_turn_id: string | null;
  stream_url: string | null;
}

/** The persona and person come from the signed-in session; only the course is sent. */
export function createSession(courseId: string): Promise<CreateSessionResult> {
  return apiJson("/api/session", { method: "POST", json: { course_id: courseId } });
}

export function converse(
  sessionId: string,
  message: string
): Promise<{ turn_id: string; stream_url: string }> {
  return apiJson("/api/converse", {
    method: "POST",
    json: { session_id: sessionId, message },
  });
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
  await apiJson<unknown>("/api/approval", {
    method: "POST",
    json: {
      session_id: params.sessionId,
      turn_id: params.turnId,
      approval_id: params.approvalId,
      decision: params.decision,
      ...(params.editedPayload && { edited_payload: params.editedPayload }),
      ...(params.note && { note: params.note }),
    },
  });
}

export async function submitClarification(params: {
  sessionId: string;
  turnId: string;
  answer: string;
}): Promise<void> {
  await apiJson<unknown>("/api/clarify", {
    method: "POST",
    json: {
      session_id: params.sessionId,
      turn_id: params.turnId,
      answer: params.answer,
    },
  });
}

export interface PodcastResult {
  podcast_id: string;
  audio_url: string;
  script: string;
  segment_count: number;
  title: string;
  error?: string;
}

/** personId must be the signed-in person's id from /me. */
export function generatePodcast(
  personId: string,
  courseId: string,
  sessionId?: string,
  conceptIds?: string[]
): Promise<PodcastResult> {
  return apiJson("/api/generate-podcast", {
    method: "POST",
    json: {
      person_id: personId,
      course_id: courseId,
      ...(sessionId && { session_id: sessionId }),
      ...(conceptIds && { concept_ids: conceptIds }),
    },
  });
}

export function getSessionHistory(sessionId: string): Promise<{ turns: unknown[] }> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/history`);
}
