import { test, expect } from "@playwright/test";
import { setupMockAPI, selectPersonaAndCourse } from "./fixtures/setup";
import { scenario10Events } from "./fixtures/mock-events";

const SESSION_ID = "s10-session";
const TURN_ID = "s10-turn";

test.describe("Scenario 10: Multi-agent study guide + send", () => {
  test("shows multiple agents in activity and approval for send", async ({
    page,
  }) => {
    await setupMockAPI(page, {
      sessionId: SESSION_ID,
      turnId: TURN_ID,
      sseEvents: scenario10Events(SESSION_ID, TURN_ID),
    });

    await page.goto("/");
    await selectPersonaAndCourse(page, "faculty");

    // Send the multi-agent request
    const input = page.locator('input[placeholder="Type a message..."]');
    await input.fill(
      "For students struggling with Ch 5, make a tailored study guide and send it."
    );
    await page.locator('button:text("Send")').click();

    // Should show plan_then_execute strategy in activity
    await expect(
      page.locator("aside").getByText("plan_then_execute")
    ).toBeVisible({ timeout: 5000 });

    // Multiple agents should be visible (exact match in agent name spans)
    await expect(
      page.locator("aside").getByText("early_alert", { exact: true })
    ).toBeVisible();
    await expect(
      page.locator("aside").getByText("content_generator", { exact: true })
    ).toBeVisible();

    // Tool call from early_alert should be visible
    await expect(
      page.locator("code", { hasText: "analytics.query" })
    ).toBeVisible();

    // Approval gate for sending the message
    await expect(
      page.getByText("Send study guide to 5 students")
    ).toBeVisible({ timeout: 5000 });

    // Approve/Reject buttons visible
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  });
});
