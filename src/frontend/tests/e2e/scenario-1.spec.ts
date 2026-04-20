import { test, expect } from "@playwright/test";
import { setupMockAPI, selectPersonaAndCourse } from "./fixtures/setup";
import { scenario1Events } from "./fixtures/mock-events";

const SESSION_ID = "s1-session";
const TURN_ID = "s1-turn";

test.describe("Scenario 1: Student asks about recursion", () => {
  test("shows tutor response with reasoning and tool call in activity", async ({
    page,
  }) => {
    await setupMockAPI(page, {
      sessionId: SESSION_ID,
      turnId: TURN_ID,
      sseEvents: scenario1Events(SESSION_ID, TURN_ID),
    });

    await page.goto("/");
    await selectPersonaAndCourse(page, "student");

    // Type and send message
    const input = page.locator('input[placeholder="Type a message..."]');
    await input.fill("Can you help me understand recursion?");
    await page.locator('button:text("Send")').click();

    // User message should appear
    await expect(
      page.getByText("Can you help me understand recursion?")
    ).toBeVisible();

    // Wait for the final response containing the bold "Recursion"
    await expect(
      page.locator("strong", { hasText: "Recursion" })
    ).toBeVisible({ timeout: 5000 });

    // Activity pane should show tutor agent (use the exact agent name span)
    await expect(
      page.locator("aside").getByText("tutor", { exact: true })
    ).toBeVisible();

    // Tool call should be visible (transparency principle)
    await expect(page.locator("code", { hasText: "content.retrieve" })).toBeVisible();

    // Should show completion status
    await expect(page.locator("aside").getByText("Complete")).toBeVisible();
  });
});
