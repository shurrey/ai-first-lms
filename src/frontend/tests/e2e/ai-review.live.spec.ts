import { expect, test } from "@playwright/test";
import { login, requireLiveBackend } from "./fixtures/live-auth";
import { startCourseSession } from "./fixtures/live-scenario";

// Reads seeded provenance only and sends no chat turn, so it makes no model calls.

test.describe("AI Review (MeasurementCanvas) on the live stack", () => {
  test.beforeEach(() => requireLiveBackend());

  test("Dr. Torres sees non-empty acceptance and edit rates for CS 101", async ({ page }) => {
    await login(page, "m.torres@university.edu");
    await startCourseSession(page, "cs101");
    await page.getByRole("button", { name: "Open AI Review" }).click();

    const dialog = page.getByRole("dialog", { name: "AI Review" });
    const rates = dialog.getByRole("table", { name: /Acceptance, edit and reject rates/ });
    await expect(rates.getByRole("row").nth(1)).toContainText(/\d+%/);
    await expect(dialog.getByRole("link", { name: "Export all tables (JSON)" })).toBeVisible();

    const text = await page.locator("body").innerText();
    expect(text).not.toMatch(/companion|Thinking/i);
  });
});
