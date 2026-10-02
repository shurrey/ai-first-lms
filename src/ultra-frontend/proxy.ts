import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route guard: no `lms_session` cookie means not signed in. The cookie is only a
 * presence check here; the engine validates it, and a 401 from any API call
 * sends the browser back to /login from the client.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (pathname === "/login" || request.cookies.has("lms_session")) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/|__nextjs|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
