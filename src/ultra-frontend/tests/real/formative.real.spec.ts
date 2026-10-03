import AxeBuilder from "@axe-core/playwright";
import { expect, request, test, type Page } from "@playwright/test";
import { ENGINE_URL, login, requireSeedPassword } from "./login";

// Needs a seeded stack. Loads the formative-loop pages for each role without starting a turn,
// so no model is called.

const ENG102 = /ENG 102/;

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function expectNoSeriousAxe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

async function openEng102(page: Page): Promise<string> {
  await page.goto("/");
  await page.getByRole("link", { name: ENG102 }).first().click();
  await expect(page).toHaveURL(/\/course\/[^/]+$/);
  return page.url();
}

const tab = (page: Page, name: string) => page.getByRole("navigation", { name: "Course" }).getByRole("link", { name });

test("Emma's ENG 102 assignment pages load without errors", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, "emma.smith@student.edu");
  await openEng102(page);
  await tab(page, "Assignments").click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectNoSeriousAxe(page);
  await page.getByRole("main").getByRole("link", { name: /Version \d+ \((draft|final)\)/ }).first().click();
  await expect(page.getByRole("region", { name: /Feedback on version/ })).toBeVisible();
  await expectNoSeriousAxe(page);
  expect(errors).toEqual([]);
});

test("Dr. Watson's Review Queue and Improvement load without errors", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, "e.watson@university.edu");
  await openEng102(page);
  await tab(page, "Review Queue").click();
  await expect(page.getByRole("heading", { name: "Review Queue" })).toBeVisible();
  await expect(page.getByText(/Loading/)).toHaveCount(0);
  await expectNoSeriousAxe(page);
  await tab(page, "Improvement").click();
  await expect(page.getByText(/Plateaued/).first()).toBeVisible();
  await expect(page.getByText(/Regressed/).first()).toBeVisible();
  await expectNoSeriousAxe(page);
  expect(errors).toEqual([]);
});

test("Dr. Hayes reads a learner's access log without errors", async ({ page }) => {
  const errors = watchConsole(page);
  const api = await request.newContext();
  const emma = await api.post(`${ENGINE_URL}/api/auth/login`, {
    data: { username: "emma.smith@student.edu", password: requireSeedPassword() },
  });
  const emmaId = (await emma.json()).person.id as string;
  await api.dispose();
  await login(page, "r.hayes@university.edu");
  await page.goto(`/learners/${emmaId}/access-log`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText(/Loading/)).toHaveCount(0);
  await expectNoSeriousAxe(page);
  expect(errors).toEqual([]);
});
