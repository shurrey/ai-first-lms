import { expect, test } from "@playwright/test";
import { login } from "./login";

test("one login is shared with the Ultra UI", async ({ page }) => {
  const me = await login(page, "emma.smith@student.edu");

  await page.goto("/");

  await expect(page.getByRole("button", { name: new RegExp(`Account menu: ${me.person.display_name}`) })).toBeVisible();
});

test("Dr. Chen sees only MATH 201", async ({ page }) => {
  await login(page, "s.chen@university.edu");

  await page.goto("/");

  await expect(page.getByRole("link", { name: /MATH 201/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /CS 101|ENG 102|BIO 150/ })).toHaveCount(0);
});
