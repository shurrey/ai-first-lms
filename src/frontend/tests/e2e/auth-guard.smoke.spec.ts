import { expect, test } from "@playwright/test";
import { EMMA, mockAuth } from "./fixtures/fake-api";

test.describe("Route guard", () => {
  test("redirects to /login when there is no lms_session cookie", async ({ page }) => {
    await mockAuth(page, { me: null });
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("keeps the requested URL in ?next=", async ({ page }) => {
    await mockAuth(page, { me: null });
    await page.goto("/?course=cs101");
    await expect(page).toHaveURL(/\/login\?next=%2F%3Fcourse%3Dcs101$/);
  });

  test("a 401 from /api/auth/me sends a stale cookie back to /login", async ({ page }) => {
    // The cookie exists, so the server-side guard lets the request through; the API rejects it.
    await mockAuth(page, { me: null, signedIn: true });
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("signed-in users reach the app", async ({ page }) => {
    await mockAuth(page, { me: EMMA });
    await page.goto("/");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("account-menu-button")).toContainText("Emma Smith");
  });
});
