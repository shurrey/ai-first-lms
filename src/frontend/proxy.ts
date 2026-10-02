import { NextResponse, type NextRequest } from "next/server";

/**
 * Route guard: no lms_session cookie means not signed in. The cookie is set by
 * the orchestrator on host localhost; cookies are not port-scoped, so this server
 * sees it. Presence only — the orchestrator validates it on every API call.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname === "/login" || request.cookies.has("lms_session")) return NextResponse.next();

  const url = request.nextUrl.clone();
  const next = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  url.pathname = "/login";
  url.search = next === "/" ? "" : `?next=${encodeURIComponent(next)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|ico)$).*)"],
};
