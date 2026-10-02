import { readFileSync } from "node:fs";
import { expect, test, type Download, type Page } from "@playwright/test";
import { login } from "./login";

// Needs a seeded stack: the seed's provenance history gives CS 101 decided AI actions.

const tabs = (page: Page) => page.getByRole("navigation", { name: "Course" }).getByRole("link");

async function openCs101AiReview(page: Page) {
  await login(page, "m.torres@university.edu");
  await page.goto("/");
  await page.getByRole("link", { name: /CS 101/ }).first().click();
  await tabs(page).filter({ hasText: "AI Review" }).click();
  await expect(page.getByRole("heading", { name: "AI Review", exact: true })).toBeVisible();
}

async function downloaded(download: Download): Promise<string> {
  return readFileSync(await download.path(), "utf8");
}

function rateValue(page: Page, label: string) {
  return page.locator("dt", { hasText: new RegExp(`^${label}$`) }).locator("..").locator("dd");
}

test("Dr. Torres sees non-empty acceptance and edit rates for CS 101", async ({ page }) => {
  await openCs101AiReview(page);

  for (const label of ["Acceptance rate", "Edit rate"]) {
    await expect(rateValue(page, label)).toHaveText(/\d+%/);
  }
  const rates = page.getByRole("table", { name: /Decision counts and rates by agent and action type/ });
  await expect(rates.getByRole("row").nth(1)).toContainText(/\d+%/);
});

test("Dr. Torres exports CS 101 measurement as JSON and CSV", async ({ page }) => {
  await openCs101AiReview(page);

  const [json] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "JSON (all tables)" }).click(),
  ]);
  const body = JSON.parse(await downloaded(json));
  expect(body.ai_actions.length).toBeGreaterThan(0);
  expect(body.human_decisions.length).toBeGreaterThan(0);

  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "CSV: decisions" }).click(),
  ]);
  const text = await downloaded(csv);
  expect(text.split("\n").filter(Boolean).length).toBeGreaterThan(1);
});

test("shipped Ultra pages contain no anthropomorphic UI strings", async ({ page }) => {
  await openCs101AiReview(page);
  const course = page.url().replace(/\/ai-review$/, "");
  for (const path of ["", "/ai-review", "/analytics", "/credentials"]) {
    await page.goto(course + path);
    await expect(page.locator("main")).toBeVisible();
    const text = await page.locator("body").innerText();
    expect(text).not.toMatch(/companion|Thinking/i);
  }
});
