import { test, expect } from "@playwright/test";
import { login, requireLiveBackend } from "./fixtures/live-auth";
import { expectActiveRole, loadScenario, runTurn, startCourseSession, toolCallsRun } from "./fixtures/live-scenario";

const scenario = loadScenario(3);

test.describe("Scenario 3: Faculty grades with rubric", () => {
  test.beforeEach(() => requireLiveBackend());

  test("grades wait behind an approval gate, then commit", async ({ page }) => {
    // Mirrors the scenario YAML's xfail, so the spec flips when the YAML does.
    test.fail(!!scenario.xfail, scenario.xfail ?? "");
    await login(page, scenario.loginAs);
    await expectActiveRole(page, scenario.activeRole);
    await startCourseSession(page, scenario.courseSlug);

    const { approvedActions } = await runTurn(page, scenario.message, scenario.approvals);

    expect(approvedActions).toHaveLength(scenario.approvals);
    expect(await toolCallsRun(page)).toContainEqual(expect.stringMatching(/^assessments\./));
  });
});
