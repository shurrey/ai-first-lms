import type { Page } from "@playwright/test";
import { api, fulfill, mockAuth, mockCreateSession, type FakeMe } from "./fake-api";

/**
 * Signs `me` in against the fake API and mocks the conversation endpoints.
 * `sseEvents` is served as one SSE body for any /api/stream request.
 */
export async function setupMockAPI(
  page: Page,
  options: {
    me: FakeMe;
    sessionId?: string;
    turnId?: string;
    sseEvents?: object[];
  }
) {
  const sessionId = options.sessionId ?? "test-session-1";
  const turnId = options.turnId ?? "test-turn-1";

  await mockAuth(page, { me: options.me });
  await mockCreateSession(page, sessionId);

  await page.route(api("/api/converse"), (route) =>
    fulfill(route, 202, {
      turn_id: turnId,
      stream_url: `/api/stream?session_id=${sessionId}&turn_id=${turnId}`,
    })
  );

  if (options.sseEvents) {
    const sseBody = options.sseEvents.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
    await page.route(`${api("/api/stream")}**`, async (route) => {
      if (route.request().method() === "OPTIONS") return fulfill(route, 204);
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          "access-control-allow-origin": new URL(page.url()).origin,
          "access-control-allow-credentials": "true",
        },
        body: sseBody,
      });
    });
  }

  await page.route(api("/api/approval"), (route) => fulfill(route, 202));
  await page.route(api("/api/clarify"), (route) => fulfill(route, 202));
  await page.route(`${api("/api/sessions/")}*/history`, (route) => fulfill(route, 200, { turns: [] }));
}

/** Picks the first enrolled course (or the scope entry for advisor/admin) to start a session. */
export async function selectCourse(page: Page, optionIndex: number = 1) {
  const courseSelect = page.locator("#course-select");
  await courseSelect.waitFor({ state: "visible", timeout: 30000 });
  const value = await courseSelect.locator("option").nth(optionIndex).getAttribute("value");
  if (!value) throw new Error(`No course option at index ${optionIndex}`);
  const created = page.waitForResponse((r) => r.url() === api("/api/session") && r.request().method() === "POST");
  await courseSelect.selectOption(value);
  await created;
}
