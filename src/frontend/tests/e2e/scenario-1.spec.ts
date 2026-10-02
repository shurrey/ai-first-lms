import { test, expect } from "@playwright/test";
import { setupMockAPI, selectCourse, expectToolCall } from "./fixtures/setup";
import { EMMA } from "./fixtures/fake-api";
import { scenario1Events } from "./fixtures/mock-events";

const SESSION_ID = "s1-session";
const TURN_ID = "s1-turn";

test.describe("Scenario 1: Student asks about recursion", () => {
  test("shows tutor response with reasoning and tool call in activity", async ({
    page,
  }) => {
    await setupMockAPI(page, {
      me: EMMA,
      sessionId: SESSION_ID,
      turnId: TURN_ID,
      sseEvents: scenario1Events(SESSION_ID, TURN_ID),
    });

    await page.goto("/");
    await selectCourse(page);

    // Type and send message
    const input = page.getByPlaceholder(/Type a message/);
    await input.fill("Can you help me understand recursion?");
    await page.getByRole("button", { name: "Send" }).click();

    // User message should appear
    await expect(
      page.getByText("Can you help me understand recursion?")
    ).toBeVisible();

    // Wait for the final response containing the bold "Recursion"
    await expect(
      page.locator("strong", { hasText: "Recursion" })
    ).toBeVisible({ timeout: 5000 });

    // Tool call should be visible (transparency principle)
    await expectToolCall(page, "content.retrieve");
  });
});
