import { test, expect } from "@playwright/test";
import { login, requireLiveBackend } from "./fixtures/live-auth";
import { expectActiveRole, loadScenario, runTurn, startCourseSession, toolCallsRun } from "./fixtures/live-scenario";

const scenario = loadScenario(1);

test.describe("Scenario 1: Student asks about recursion", () => {
  test.beforeEach(() => requireLiveBackend());

  test("the tutor answers with provenance and shows the tools it ran", async ({ page }) => {
    await login(page, scenario.loginAs);
    await expectActiveRole(page, scenario.activeRole);
    await startCourseSession(page, scenario.courseSlug);

    await runTurn(page, scenario);

    expect(await toolCallsRun(page)).not.toHaveLength(0);
  });
});
