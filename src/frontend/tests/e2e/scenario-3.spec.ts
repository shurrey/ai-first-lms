import { test, expect } from "@playwright/test";
import { setupMockAPI, selectPersonaAndCourse } from "./fixtures/setup";
import { scenario3Events } from "./fixtures/mock-events";

const SESSION_ID = "s3-session";
const TURN_ID = "s3-turn";

test.describe("Scenario 3: Faculty grades with rubric", () => {
  test("shows rubric canvas and approval gate", async ({ page }) => {
    await setupMockAPI(page, {
      sessionId: SESSION_ID,
      turnId: TURN_ID,
      sseEvents: scenario3Events(SESSION_ID, TURN_ID),
    });

    await page.goto("/");
    await selectPersonaAndCourse(page, "faculty");

    // Send grading request
    const input = page.locator('input[placeholder="Type a message..."]');
    await input.fill("Grade submissions for Essay 3 with my rubric.");
    await page.locator('button:text("Send")').click();

    // Activity pane should show grading_assistant agent
    await expect(
      page.locator("aside").getByText("grading_assistant", { exact: true })
    ).toBeVisible({ timeout: 5000 });

    // Tool call should be visible
    await expect(
      page.locator("code", { hasText: "assessments.rubrics" })
    ).toBeVisible();

    // Approval gate should appear
    await expect(
      page.getByText("Commit grades for 23 students")
    ).toBeVisible({ timeout: 5000 });

    // Should have approve/edit/reject buttons
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();

    // Rubric canvas should show "Awaiting Approval" badge
    await expect(page.getByText("Awaiting Approval")).toBeVisible();
  });
});
