import { test, expect, type Page } from "@playwright/test";
import { setupMockAPI, selectCourse, expectToolCall } from "./fixtures/setup";
import { TORRES } from "./fixtures/fake-api";
import { scenario3Events } from "./fixtures/mock-events";

const SESSION_ID = "s3-session";
const TURN_ID = "s3-turn";

async function sendGradingRequest(page: Page) {
  await setupMockAPI(page, {
    me: TORRES,
    sessionId: SESSION_ID,
    turnId: TURN_ID,
    sseEvents: scenario3Events(SESSION_ID, TURN_ID),
  });
  await page.goto("/");
  await selectCourse(page);
  await page.getByPlaceholder(/Type a message/).fill("Grade submissions for Essay 3 with my rubric.");
  await page.getByRole("button", { name: "Send" }).click();
}

test.describe("Scenario 3: Faculty grades with rubric", () => {
  test("shows the rubric tool call", async ({ page }) => {
    await sendGradingRequest(page);
    await expectToolCall(page, "assessments.rubrics");
  });

  test("shows rubric canvas and approval gate", async ({ page }) => {
    await sendGradingRequest(page);
    await expect(page.getByText("Commit grades for 23 students")).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
    await expect(page.getByText("Awaiting Approval")).toBeVisible();
  });
});
