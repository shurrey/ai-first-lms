/** Routes this UI serves. Anything else (e.g. an Ultra-only home_route) lands on "/". */
const CHAT_ROUTES = new Set(["/"]);

/**
 * Returns `candidate` only if it is a same-origin path to a Chat UI route,
 * so ?next= cannot be used as an open redirect.
 */
export function safeInternalPath(candidate: string | null | undefined): string | null {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) return null;
  let url: URL;
  try {
    url = new URL(candidate, "http://placeholder.invalid");
  } catch {
    return null;
  }
  if (url.origin !== "http://placeholder.invalid") return null;
  if (!CHAT_ROUTES.has(url.pathname)) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Where to go after sign-in: ?next= if valid, else /me.home_route if it is ours, else "/". */
export function postLoginDestination(next: string | null, homeRoute: string | null): string {
  return safeInternalPath(next) ?? safeInternalPath(homeRoute) ?? "/";
}

export function loginUrl(next?: string): string {
  const target = safeInternalPath(next);
  return target && target !== "/" ? `/login?next=${encodeURIComponent(target)}` : "/login";
}

/** Full navigation (not router.push) so all in-memory session state is discarded. */
export function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  const here = `${window.location.pathname}${window.location.search}`;
  window.location.assign(loginUrl(here));
}
