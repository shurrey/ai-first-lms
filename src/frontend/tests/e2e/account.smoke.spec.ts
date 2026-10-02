import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  CS101_ID,
  CSRF_TOKEN,
  EMMA,
  HAYES,
  OKAFOR,
  TORRES,
  TORRES_AS_PROGRAM_LEAD,
  api,
  fulfill,
  mockAuth,
  mockCreateSession,
} from "./fixtures/fake-api";

test.describe("Header and course selector", () => {
  test("lists only /me enrollments and no persona picker", async ({ page }) => {
    await mockAuth(page, { me: EMMA });
    await page.goto("/");
    await expect(page.getByLabel("Course")).toBeVisible();
    await expect(page.locator("#course-select option")).toHaveText([
      "Select a course...",
      "CS 101 — Intro to Computer Science",
      "MATH 201 — Linear Algebra",
    ]);
    await expect(page.locator("#persona-select")).toHaveCount(0);
    await expect(page.getByRole("combobox")).toHaveCount(1);
  });

  test("advisor and admin get a scope entry instead of a course list", async ({ page }) => {
    await mockAuth(page, { me: OKAFOR });
    await page.goto("/");
    await expect(page.locator("#course-select option")).toHaveText(["Select a course...", "All my students"]);
  });

  test("admin scope entry is Institution", async ({ page }) => {
    await mockAuth(page, { me: HAYES });
    await page.goto("/");
    await expect(page.locator("#course-select option")).toHaveText(["Select a course...", "Institution"]);
  });

  test("POST /api/session sends only course_id, with the CSRF header and cookies", async ({ page }) => {
    const auth = await mockAuth(page, { me: EMMA });
    await mockCreateSession(page);
    await page.goto("/");
    const req = page.waitForRequest((r) => r.url() === api("/api/session") && r.method() === "POST");
    await page.getByLabel("Course").selectOption(CS101_ID);
    const sent = await req;
    expect(sent.postDataJSON()).toEqual({ course_id: CS101_ID });
    expect(sent.headers()["x-csrf-token"]).toBe(CSRF_TOKEN);
    expect(auth.requests.some((r) => r.url() === api("/api/auth/me"))).toBe(true);
  });
});

test.describe("Account menu", () => {
  test("is keyboard operable and hides Switch role for a single-role person", async ({ page }) => {
    await mockAuth(page, { me: EMMA });
    await page.goto("/");
    const button = page.getByTestId("account-menu-button");
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    const menu = page.getByRole("menu");
    await expect(menu.getByRole("menuitem")).toHaveText(["Change password", "Sign out"]);
    await expect(menu.getByRole("menuitemradio")).toHaveCount(0);
    await expect(menu.getByRole("menuitem", { name: "Change password" })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(menu.getByRole("menuitem", { name: "Sign out" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(button).toBeFocused();
  });

  test("Switch role lists only own roles and switches via POST /api/auth/role", async ({ page }) => {
    await mockAuth(page, { me: TORRES, roleSwitch: { program_lead: TORRES_AS_PROGRAM_LEAD } });
    await page.goto("/");
    await page.getByTestId("account-menu-button").click();
    const roles = page.getByRole("menuitemradio");
    await expect(roles).toHaveText([/Faculty/, /Program Lead/]);
    await expect(page.getByRole("menuitemradio", { name: /Faculty/ })).toHaveAttribute("aria-checked", "true");

    const req = page.waitForRequest((r) => r.url() === api("/api/auth/role") && r.method() === "POST");
    await page.getByRole("menuitemradio", { name: /Program Lead/ }).click();
    const sent = await req;
    expect(sent.postDataJSON()).toEqual({ role: "program_lead" });
    expect(sent.headers()["x-csrf-token"]).toBe(CSRF_TOKEN);
    await expect(page.getByTestId("account-menu-button")).toContainText("Program Lead");
  });

  test("Sign out posts logout and returns to /login", async ({ page }) => {
    await mockAuth(page, { me: EMMA });
    await page.goto("/");
    await page.getByTestId("account-menu-button").click();
    const req = page.waitForRequest((r) => r.url() === api("/api/auth/logout") && r.method() === "POST");
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    expect((await req).headers()["x-csrf-token"]).toBe(CSRF_TOKEN);
    await expect(page).toHaveURL(/\/login$/);
  });

  test("Change password validates and reports the server's answer", async ({ page }) => {
    await mockAuth(page, { me: EMMA });
    await page.goto("/");
    await page.getByTestId("account-menu-button").click();
    await page.getByRole("menuitem", { name: "Change password" }).click();
    const dialog = page.getByRole("dialog", { name: "Change password" });
    await expect(dialog).toBeVisible();

    await dialog.getByLabel("Current password").fill("wrong current pw");
    await dialog.getByLabel("New password", { exact: true }).fill("short");
    await dialog.getByLabel("Confirm new password").fill("short");
    await dialog.getByRole("button", { name: "Change password" }).click();
    await expect(dialog.getByRole("alert")).toHaveText("New password must be at least 12 characters.");

    await dialog.getByLabel("New password", { exact: true }).fill("a-much-longer-password");
    await dialog.getByLabel("Confirm new password").fill("a-different-password");
    await dialog.getByRole("button", { name: "Change password" }).click();
    await expect(dialog.getByRole("alert")).toHaveText("New passwords don't match.");

    await dialog.getByLabel("Confirm new password").fill("a-much-longer-password");
    await dialog.getByRole("button", { name: "Change password" }).click();
    await expect(dialog.getByRole("alert")).toHaveText("Current password is incorrect.");

    await dialog.getByLabel("Current password").fill("correct horse battery");
    await dialog.getByRole("button", { name: "Change password" }).click();
    await expect(dialog.getByRole("status")).toHaveText("Password changed.");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("opens Change password on its own when must_change_password is set", async ({ page }) => {
    await mockAuth(page, { me: { ...EMMA, must_change_password: true } });
    await page.goto("/");
    await expect(page.getByRole("dialog", { name: "Change password" })).toBeVisible();
  });

  test("signed-in page with the menu open has no serious or critical axe violations", async ({ page }) => {
    await mockAuth(page, { me: TORRES });
    await page.goto("/");
    await page.getByTestId("account-menu-button").click();
    await expect(page.getByRole("menu")).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .include("header")
      .analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(
      serious.map((v) => `${v.id}: ${v.nodes.map((n) => `${n.target.join(" ")} ${n.failureSummary ?? ""}`).join("; ")}`)
    ).toEqual([]);
  });
});

test.describe("Capabilities and 403", () => {
  test("a 403 roster shows an accessible no-access state", async ({ page }) => {
    await mockAuth(page, { me: TORRES });
    await mockCreateSession(page);
    await page.route(api(`/api/roster/${CS101_ID}`), (route) => fulfill(route, 403, { detail: "Forbidden" }));
    await page.goto("/");
    await page.getByLabel("Course").selectOption(CS101_ID);
    await page.getByRole("button", { name: "Roster" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "You don't have access to this." })).toBeVisible();
  });

  test("controls without a capability are not rendered", async ({ page }) => {
    await mockAuth(page, { me: EMMA });
    await mockCreateSession(page);
    await page.goto("/");
    await page.getByLabel("Course").selectOption(CS101_ID);
    await expect(page.getByRole("button", { name: "Roster" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Settings" })).toHaveCount(0);
  });
});
