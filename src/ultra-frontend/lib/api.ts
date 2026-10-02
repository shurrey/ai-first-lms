export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Dispatched on window when an API call returns 403; AccessBoundary renders the no-access state. */
export const FORBIDDEN_EVENT = "lms:forbidden";

export const CSRF_COOKIE = "lms_csrf";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiFetchInit extends RequestInit {
  /** false: a 401 is returned to the caller instead of redirecting to /login. */
  redirectOn401?: boolean;
  /** false: a 403 is returned to the caller instead of showing the page-level no-access state. */
  reportForbidden?: boolean;
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) return decodeURIComponent(part.slice(eq + 1).trim());
  }
  return null;
}

// URL parsing strips tab/CR/LF and treats "\\" as "/", so "/\t/host" would otherwise resolve as "//host".
const UNSAFE_PATH_CHARS = /[\u0000-\u001f\u007f\\]/;

/**
 * Returns `next` as a same-origin path+search+hash, or null if it is absent,
 * off-origin, or /login. `origin` defaults to the current page's origin.
 */
export function safeNextPath(next: string | null | undefined, origin?: string): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || UNSAFE_PATH_CHARS.test(next)) return null;
  const base = origin ?? (typeof window === "undefined" ? null : window.location.origin);
  if (!base) return null;
  let url: URL;
  try {
    url = new URL(next, base);
  } catch {
    return null;
  }
  if (url.origin !== new URL(base).origin) return null;
  if (!url.pathname.startsWith("/") || url.pathname.startsWith("//") || decodesUnsafe(url.pathname)) return null;
  if (url.pathname === "/login") return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Rejects encodings such as "/%2F%2Fhost" or "/%09/host" that a later decode would turn off-origin. */
function decodesUnsafe(pathname: string): boolean {
  let decoded: string;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return true;
  }
  return decoded.startsWith("//") || UNSAFE_PATH_CHARS.test(decoded);
}

const KNOWN_ROUTE_PREFIXES = ["/course/", "/account/"];

/**
 * The server's home_route as a safe same-origin path. Role homes are not built in the Ultra UI
 * yet, so anything outside a known prefix (or unsafe) falls back to the course list.
 */
export function resolveHomeRoute(homeRoute: string | null | undefined, origin?: string): string {
  const path = safeNextPath(homeRoute, origin);
  if (!path) return "/";
  return KNOWN_ROUTE_PREFIXES.some((p) => path.startsWith(p)) ? path : "/";
}

export function loginUrl(): string {
  const here = `${window.location.pathname}${window.location.search}`;
  const next = safeNextPath(here);
  return next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login";
}

/**
 * fetch against the engine with the session cookie, plus X-CSRF-Token on non-GET.
 * 401 navigates to /login?next=… and 403 raises FORBIDDEN_EVENT (both then throw
 * ApiError) unless the caller opts out; other statuses are returned unchanged.
 */
export async function apiFetch(path: string, init: ApiFetchInit = {}): Promise<Response> {
  const { redirectOn401 = true, reportForbidden = true, ...requestInit } = init;
  const method = (requestInit.method ?? "GET").toUpperCase();
  // A 403 counts against the page that made the request, not one navigated to since.
  const origin = typeof window === "undefined" ? "" : window.location.pathname;
  const headers = new Headers(requestInit.headers);
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...requestInit, method, headers, credentials: "include" });

  if (res.status === 401 && redirectOn401) {
    window.location.assign(loginUrl());
    throw new ApiError(401, "Not signed in");
  }
  if (res.status === 403 && reportForbidden) {
    window.dispatchEvent(new CustomEvent(FORBIDDEN_EVENT, { detail: { path, origin } }));
    throw new ApiError(403, "Forbidden");
  }
  return res;
}

/** apiFetch, then parse JSON; any non-2xx becomes an ApiError carrying the response's `detail`. */
export async function apiJson<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res));
  return (await res.json()) as T;
}

async function errorDetail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Non-JSON error bodies fall through to the status line.
  }
  return `${res.status} ${res.statusText}`.trim();
}
