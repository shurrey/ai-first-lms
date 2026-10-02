import { expect, test, type Page } from "@playwright/test";

/**
 * Real-backend sign-in for live specs. Every seeded account shares SEED_DEMO_PASSWORD
 * (spec §4.3); the value is read from the environment only.
 */
export function isLiveRun(): boolean {
  return process.env.E2E_LIVE === "1" || !!process.env.E2E_BASE_URL;
}

export function requireLiveBackend() {
  test.skip(!process.env.SEED_DEMO_PASSWORD, "SEED_DEMO_PASSWORD is not set");
  test.skip(!isLiveRun(), "Set E2E_LIVE=1 (or E2E_BASE_URL) to run live specs against a running stack");
}

export async function login(page: Page, username: string): Promise<void> {
  const password = process.env.SEED_DEMO_PASSWORD;
  if (!password) throw new Error("SEED_DEMO_PASSWORD is not set");
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname !== "/login");
  await expect(page.getByTestId("account-menu-button")).toBeVisible();
}
