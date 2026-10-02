import { test, expect } from "@playwright/test";
import { setupMockAPI, selectCourse } from "./fixtures/setup";
import { EMMA } from "./fixtures/fake-api";
import { scenario11Events } from "./fixtures/mock-events";

const SESSION_ID = "s11-session";
const TURN_ID = "s11-turn";

test.describe("Scenario 11: Student learning path (AI-native)", () => {
  test("shows the learning path answer", async ({ page }) => {
    await setupMockAPI(page, {
      me: EMMA,
      sessionId: SESSION_ID,
      turnId: TURN_ID,
      sseEvents: scenario11Events(SESSION_ID, TURN_ID),
    });

    await page.goto("/");
    await selectCourse(page);

    // Send the learning path request
    const input = page.getByPlaceholder(/Type a message/);
    await input.fill(
      "I want to get better at writing. Help me build a path."
    );
    await page.getByRole("button", { name: "Send" }).click();

    // Final answer should appear in main chat area
    await expect(
      page.locator("main").getByText("personalized writing improvement path")
    ).toBeVisible({ timeout: 5000 });
  });
});
