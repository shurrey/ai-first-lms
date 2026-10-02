import type { FullConfig } from "@playwright/test";

const ROUTES = ["/", "/login", "/account/password", "/course/warm", "/course/warm/roster", "/course/warm/gradebook",
  "/course/warm/analytics", "/course/warm/credentials", "/course/warm/calendar", "/course/warm/ai-review"];

/**
 * next dev compiles a route on first request; parallel workers hitting an
 * uncompiled dynamic route at the same moment can be served a 404.
 */
export default async function warmRoutes(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL;
  for (const route of ROUTES) {
    const res = await fetch(`${baseURL}${route}`, { headers: { cookie: "lms_session=warmup" }, redirect: "manual" });
    if (res.status >= 500) throw new Error(`Warm-up of ${route} failed with ${res.status}`);
  }
}
