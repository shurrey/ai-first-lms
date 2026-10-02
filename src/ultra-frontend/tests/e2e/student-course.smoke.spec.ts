import { expect, test } from "@playwright/test";
import { CS101_ID, EMMA_ME, mockEngine, setSessionCookies } from "./fake-api";

test("student course page renders the mastery map", async ({ page, context, baseURL }) => {
  await setSessionCookies(context, baseURL!);
  const engine = await mockEngine(page, { me: EMMA_ME });

  await page.goto(`/course/${CS101_ID}`);

  await expect(page.getByRole("button", { name: /Account menu: Emma Smith, Student/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your Mastery Progress" })).toBeVisible();
  await expect(page.getByText("of 4 concepts")).toBeVisible();
  await expect(page.getByText("Variables and Assignment")).toBeVisible();
  await expect(page.getByText("Type Conversion", { exact: true })).toBeVisible();
  await expect(page.getByText("Master Type Conversion before the midterm")).toBeVisible();
  await expect(page.getByText("You learn fastest from worked examples.")).toBeVisible();
  await expect(page.locator(".animate-pulse")).toHaveCount(0);

  expect(engine.unhandled).toEqual([]);
});
