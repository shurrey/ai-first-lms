import { test, expect } from "@playwright/test";
import { setupMockAPI, selectPersonaAndCourse } from "./fixtures/setup";
import { scenario11Events } from "./fixtures/mock-events";

const SESSION_ID = "s11-session";
const TURN_ID = "s11-turn";

test.describe("Scenario 11: Student learning path (AI-native)", () => {
  test("shows learning path canvas with mastery nodes", async ({ page }) => {
    await setupMockAPI(page, {
      sessionId: SESSION_ID,
      turnId: TURN_ID,
      sseEvents: scenario11Events(SESSION_ID, TURN_ID),
    });

    await page.goto("/");
    await selectPersonaAndCourse(page, "student");

    // Send the learning path request
    const input = page.locator('input[placeholder="Type a message..."]');
    await input.fill(
      "I want to get better at writing. Help me build a path."
    );
    await page.locator('button:text("Send")').click();

    // Should show advising and tutor agents in activity
    await expect(
      page.locator("aside").getByText("advising", { exact: true })
    ).toBeVisible({ timeout: 5000 });
    await expect(
      page.locator("aside").getByText("tutor", { exact: true })
    ).toBeVisible();

    // Final answer should appear in main chat area
    await expect(
      page.locator("main").getByText("personalized writing improvement path")
    ).toBeVisible({ timeout: 5000 });

    // Learning path canvas should render in the aside
    await expect(
      page.getByRole("heading", { name: "Writing Improvement Path" })
    ).toBeVisible();

    // Should show mastery nodes
    await expect(page.getByText("Grammar Fundamentals")).toBeVisible();
    await expect(page.getByText("Essay Structure").first()).toBeVisible();
    await expect(page.getByText("Argumentation").first()).toBeVisible();

    // Should show recommended next
    await expect(page.getByText("Recommended Next")).toBeVisible();

    // Should show completion
    await expect(page.locator("aside").getByText("Complete")).toBeVisible();
  });
});
