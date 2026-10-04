import { chromium, type FullConfig } from "@playwright/test";

const ROUTES = ["/", "/login", "/account/password", "/course/warm", "/course/warm/roster", "/course/warm/gradebook",
  "/course/warm/analytics", "/course/warm/credentials", "/course/warm/calendar", "/course/warm/ai-review", "/course/warm/assignments", "/course/warm/assignments/warm",
  "/course/warm/review", "/course/warm/improvement", "/course/warm/practice/warm", "/course/warm/alignment/warm", "/learners/warm/access-log"];

/**
 * next dev compiles a route on first request; parallel workers hitting an
 * uncompiled dynamic route at the same moment can be served a 404, or a client
 * chunk that is still being written (a browser SyntaxError). A fetch compiles the
 * server side; one browser visit per route compiles the client chunks too.
 */
export default async function warmRoutes(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!;
  for (const route of ROUTES) {
    const res = await fetch(`${baseURL}${route}`, { headers: { cookie: "lms_session=warmup" }, redirect: "manual" });
    if (res.status >= 500) throw new Error(`Warm-up of ${route} failed with ${res.status}`);
  }
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ baseURL });
    await context.addCookies([{ name: "lms_session", value: "warmup", url: baseURL }]);
    const page = await context.newPage();
    // The fake engine isn't mocked here; API calls fail fast and only the chunks matter.
    await page.route((url) => !url.href.startsWith(baseURL), (route) => route.abort());
    for (const route of ROUTES) {
      await page.goto(route, { waitUntil: "load" });
    }
  } finally {
    await browser.close();
  }
}
