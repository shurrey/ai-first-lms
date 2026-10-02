import { expect, test } from "@playwright/test";
import { login, requireLiveBackend } from "./fixtures/live-auth";

test.describe("Live sign-in", () => {
  test.beforeEach(() => requireLiveBackend());

  test("Emma signs in and sees only her own courses", async ({ page }) => {
    await login(page, "emma.smith@student.edu");
    await expect(page.getByTestId("account-menu-button")).toContainText("Emma Smith");
    await expect(page.getByTestId("account-menu-button")).toContainText("Student");
    await expect(page.locator("#persona-select")).toHaveCount(0);
    const options = await page.locator("#course-select option").allTextContents();
    expect(options.some((o) => o.startsWith("CS 101"))).toBe(true);
    expect(options.some((o) => o.startsWith("ENG 102"))).toBe(false);
  });

  test("Dr. Torres can switch only between her own roles", async ({ page }) => {
    await login(page, "m.torres@university.edu");
    await page.getByTestId("account-menu-button").click();
    const roles = page.getByRole("menuitemradio");
    await expect(roles).toHaveText([/Faculty/, /Program Lead/]);
  });
});
