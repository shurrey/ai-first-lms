import { expect, test } from "@playwright/test";
import { CS101_ID, mockEngine } from "./fake-api";

test("student course page renders the mastery map", async ({ page }) => {
  const unhandled = await mockEngine(page);

  await page.goto(`/course/${CS101_ID}`);

  // Persona is client state defaulting to faculty; switch through the sidebar like a user would.
  await page.getByRole("button", { name: /Dr\. Maria Torres/ }).click();
  await page.getByRole("button", { name: /Emma Smith/ }).click();

  await expect(page.getByRole("heading", { name: "Your Mastery Progress" })).toBeVisible();
  await expect(page.getByText("of 4 concepts")).toBeVisible();
  await expect(page.getByText("Variables and Assignment")).toBeVisible();
  await expect(page.getByText("Type Conversion", { exact: true })).toBeVisible();
  await expect(page.getByText("Master Type Conversion before the midterm")).toBeVisible();
  await expect(page.getByText("You learn fastest from worked examples.")).toBeVisible();
  await expect(page.locator(".animate-pulse")).toHaveCount(0);

  expect(unhandled).toEqual([]);
});
