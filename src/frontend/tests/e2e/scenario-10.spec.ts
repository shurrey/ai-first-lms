import { test, expect, type Page } from "@playwright/test";
import { setupMockAPI, selectCourse, expectToolCall } from "./fixtures/setup";
import { TORRES } from "./fixtures/fake-api";
import { scenario10Events } from "./fixtures/mock-events";

const SESSION_ID = "s10-session";
const TURN_ID = "s10-turn";

async function sendStudyGuideRequest(page: Page) {
  await setupMockAPI(page, {
    me: TORRES,
    sessionId: SESSION_ID,
    turnId: TURN_ID,
    sseEvents: scenario10Events(SESSION_ID, TURN_ID),
  });
  await page.goto("/");
  await selectCourse(page);
  await page
    .getByPlaceholder(/Type a message/)
    .fill("For students struggling with Ch 5, make a tailored study guide and send it.");
  await page.getByRole("button", { name: "Send" }).click();
}

test.describe("Scenario 10: Multi-agent study guide + send", () => {
  test("shows the early_alert tool call", async ({ page }) => {
    await sendStudyGuideRequest(page);
    await expectToolCall(page, "analytics.query");
  });

  test("shows the approval gate for sending", async ({ page }) => {
    await sendStudyGuideRequest(page);
    await expect(page.getByText("Send study guide to 5 students")).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  });
});
