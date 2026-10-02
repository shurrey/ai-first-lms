import { test, expect } from "@playwright/test";
import { login, requireLiveBackend } from "./fixtures/live-auth";
import { expectActiveRole, loadScenario, runTurn, startCourseSession } from "./fixtures/live-scenario";

const scenario = loadScenario(11);

test.describe("Scenario 11: Student learning path (AI-native)", () => {
  test.beforeEach(() => requireLiveBackend());

  test("the answer carries a learning path canvas", async ({ page }) => {
    await login(page, scenario.loginAs);
    await expectActiveRole(page, scenario.activeRole);
    await startCourseSession(page, scenario.courseSlug);

    await runTurn(page, scenario.message, scenario.approvals);

    const canvas = page.locator("main > div").first().getByTestId("canvas-shell");
    await expect(canvas.first()).toBeVisible();
    await expect(canvas.first()).toContainText("Generated");
  });
});
