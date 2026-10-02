import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { EMMA, TORRES, mockAuth, mockCreateSession } from "./fixtures/fake-api";

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
}

test.describe("Login page", () => {
  test("renders a labelled form with password-manager friendly fields", async ({ page }) => {
    await mockAuth(page, { me: null });
    await page.goto("/login");

    const username = page.getByLabel("Username");
    const password = page.getByLabel("Password", { exact: true });
    await expect(username).toHaveAttribute("autocomplete", "username");
    await expect(password).toHaveAttribute("autocomplete", "current-password");
    await expect(password).toHaveAttribute("type", "password");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await expect(page.locator("#login-error")).toHaveAttribute("role", "alert");

    await page.getByLabel("Show password").check();
    await expect(password).toHaveAttribute("type", "text");
    await page.getByLabel("Show password").uncheck();
    await expect(password).toHaveAttribute("type", "password");
  });

  test("accepts pasted credentials", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await mockAuth(page, { me: null });
    await page.goto("/login");
    const password = page.getByLabel("Password", { exact: true });
    await page.evaluate(() => navigator.clipboard.writeText("pasted-secret-value"));
    await password.focus();
    await page.keyboard.press("ControlOrMeta+V");
    await expect(password).toHaveValue("pasted-secret-value");
  });

  test("shows the generic error in role=alert on 401", async ({ page }) => {
    await mockAuth(page, { me: null, loginAs: EMMA });
    await page.goto("/login");
    await page.getByLabel("Username").fill("emma.smith@student.edu");
    await page.getByLabel("Password", { exact: true }).fill("wrong password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.locator("#login-error")).toHaveText("Invalid username or password.");
    await expect(page.getByLabel("Username")).toHaveAttribute("aria-invalid", "true");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("asks for both fields before calling the API", async ({ page }) => {
    const auth = await mockAuth(page, { me: null, loginAs: EMMA });
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator("#login-error")).toHaveText("Enter your username and password.");
    expect(auth.requests.filter((r) => r.url().endsWith("/api/auth/login"))).toHaveLength(0);
  });

  test("redirects to the app on success and shows the signed-in person", async ({ page }) => {
    await mockAuth(page, { me: null, loginAs: EMMA, signedIn: false });
    await mockCreateSession(page);
    await page.goto("/login");
    await page.getByLabel("Username").fill("emma.smith@student.edu");
    await page.getByLabel("Password", { exact: true }).fill("correct horse battery");
    await page.getByRole("button", { name: "Sign in" }).click();

    // Generous timeout: the dev server may compile "/" on first hit.
    await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
    await expect(page.getByTestId("account-menu-button")).toContainText("Emma Smith");
    await expect(page.getByTestId("account-menu-button")).toContainText("Student");
  });

  test("an Ultra-only home_route or a foreign ?next= lands on /", async ({ page }) => {
    // TORRES.home_route is "/teaching", which only the Ultra UI serves.
    await mockAuth(page, { me: null, loginAs: TORRES, signedIn: false });
    await page.goto(`/login?next=${encodeURIComponent("//evil.example/steal")}`);
    await page.getByLabel("Username").fill("m.torres@university.edu");
    await page.getByLabel("Password", { exact: true }).fill("correct horse battery");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/^http:\/\/localhost:\d+\/$/, { timeout: 30_000 });
  });

  test("has no serious or critical axe violations", async ({ page }) => {
    await mockAuth(page, { me: null, loginAs: EMMA });
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    expect(await seriousViolations(page)).toEqual([]);

    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator("#login-error")).not.toBeEmpty();
    expect(await seriousViolations(page)).toEqual([]);
  });
});
