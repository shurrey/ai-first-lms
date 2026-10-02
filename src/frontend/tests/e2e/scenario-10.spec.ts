import { test, expect } from "@playwright/test";
import { login, requireLiveBackend } from "./fixtures/live-auth";
import { expectActiveRole, loadScenario, runTurn, startCourseSession, toolCallsRun } from "./fixtures/live-scenario";

const scenario = loadScenario(10);

test.describe("Scenario 10: Multi-agent study guide + send", () => {
  test.beforeEach(() => requireLiveBackend());

  test("each write waits for its own approval before the answer arrives", async ({ page }) => {
    await login(page, scenario.loginAs);
    await expectActiveRole(page, scenario.activeRole);
    await startCourseSession(page, scenario.courseSlug);

    const { approvedActions } = await runTurn(page, scenario.message, scenario.approvals);

    expect(approvedActions).toHaveLength(scenario.approvals);
    for (const action of approvedActions) expect(action.trim()).not.toBe("");
    expect(await toolCallsRun(page)).not.toHaveLength(0);
  });
});
