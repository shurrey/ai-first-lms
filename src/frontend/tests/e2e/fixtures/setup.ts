import { type Page } from "@playwright/test";

/**
 * Set up API route mocks for a test page.
 * Intercepts all orchestrator API calls and returns mock responses.
 */
export async function setupMockAPI(
  page: Page,
  options: {
    sessionId?: string;
    turnId?: string;
    sseEvents?: Record<string, unknown>[];
  } = {}
) {
  const sessionId = options.sessionId ?? "test-session-1";
  const turnId = options.turnId ?? "test-turn-1";

  // Mock POST /api/session
  await page.route("**/api/session", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ session_id: sessionId }),
    });
  });

  // Mock POST /api/converse
  await page.route("**/api/converse", async (route) => {
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        turn_id: turnId,
        stream_url: `/api/stream?session_id=${sessionId}&turn_id=${turnId}`,
      }),
    });
  });

  // Mock GET /api/stream — SSE
  if (options.sseEvents) {
    await page.route("**/api/stream**", async (route) => {
      const events = options.sseEvents!;
      const sseBody = events
        .map((e) => `data: ${JSON.stringify(e)}\n\n`)
        .join("");

      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: {
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
        body: sseBody,
      });
    });
  }

  // Mock POST /api/approval
  await page.route("**/api/approval", async (route) => {
    await route.fulfill({ status: 202 });
  });

  // Mock POST /api/clarify
  await page.route("**/api/clarify", async (route) => {
    await route.fulfill({ status: 202 });
  });

  // Mock GET /api/sessions/*/history
  await page.route("**/api/sessions/*/history", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ turns: [] }),
    });
  });
}

/**
 * Select a persona and course in the UI to activate a session.
 */
export async function selectPersonaAndCourse(
  page: Page,
  persona: string,
  courseIndex: number = 1
) {
  // Wait for the persona select to be visible (after hydration)
  const personaSelect = page.locator("#persona-select");
  await personaSelect.waitFor({ state: "visible", timeout: 10000 });

  // Select persona
  await personaSelect.selectOption(persona);

  // Wait for the course select to be visible
  const courseSelect = page.locator("#course-select");
  await courseSelect.waitFor({ state: "visible", timeout: 5000 });

  // Select first course
  const options = await courseSelect.locator("option").all();
  if (options.length > courseIndex) {
    const value = await options[courseIndex].getAttribute("value");
    if (value) {
      await courseSelect.selectOption(value);
    }
  }

  // Wait for session creation response
  await page.waitForTimeout(500);
}
