import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { CHEN_ME, CS101_ID, EMMA_ME, MATH201_ID, OKAFOR_ME, SMOKE_CSRF, TORRES_ME, mockEngine, setSessionCookies } from "./fake-api";

test.beforeEach(async ({ context, baseURL }) => {
  await setSessionCookies(context, baseURL!);
});

test("account menu is keyboard operable and offers only the person's own other roles", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.goto("/");

  const toggle = page.getByRole("button", { name: /Account menu: Dr\. Maria Torres, Faculty/ });
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");

  const switchGroup = page.getByRole("group", { name: "Switch role" });
  await expect(switchGroup.getByRole("button")).toHaveText(["Switch to Program Lead"]);
  await expect(page.getByRole("link", { name: "Change password" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toBeFocused();

  await page.keyboard.press("Enter");
  await switchGroup.getByRole("button", { name: "Switch to Program Lead" }).click();
  await expect(page.getByRole("button", { name: /Account menu: Dr\. Maria Torres, Program Lead/ })).toBeVisible();
  // home_route "/program" is not built in the Ultra UI yet, so the switch lands on the course list.
  await expect(page).toHaveURL("/");

  const roleCall = engine.requests.find((r) => r.path === "/api/auth/role");
  expect(roleCall?.body).toEqual({ role: "program_lead" });
  expect(roleCall?.headers["x-csrf-token"]).toBe(SMOKE_CSRF);
});

test("a single-role person sees no Switch role section", async ({ page }) => {
  await mockEngine(page, { me: EMMA_ME });
  await page.goto("/");
  await page.getByRole("button", { name: /Account menu: Emma Smith/ }).click();
  await expect(page.getByRole("group", { name: "Switch role" })).toHaveCount(0);
});

test("sign out revokes the session and returns to /login", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  await page.goto("/");
  await page.getByRole("button", { name: /Account menu: Emma Smith/ }).click();
  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(page).toHaveURL("/login");
  const logout = engine.requests.find((r) => r.path === "/api/auth/logout");
  expect(logout?.method).toBe("POST");
  expect(logout?.headers["x-csrf-token"]).toBe(SMOKE_CSRF);
});

test("faculty course list comes from /me.enrollments", async ({ page }) => {
  await mockEngine(page, { me: CHEN_ME });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "MATH 201 — Linear Algebra" })).toBeVisible();
  await expect(page.getByRole("link", { name: /CS 101/ })).toHaveCount(0);
  await expect(page.getByText("1 result")).toBeVisible();
});

test("advisor gets an All my students scope entry instead of course tiles", async ({ page }) => {
  await mockEngine(page, { me: OKAFOR_ME });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "All my students" })).toBeVisible();
  await expect(page.getByText("50 assigned students")).toBeVisible();
  await page.getByRole("link", { name: "All my students" }).click();
  await expect(page).toHaveURL("/course/all");
  await expect(page.getByRole("heading", { name: "All my students", level: 2 })).toBeVisible();
});

test("a course outside the person's enrollments shows the no-access state", async ({ page }) => {
  await mockEngine(page, { me: CHEN_ME });
  await page.goto(`/course/${CS101_ID}`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeFocused();
});

test("an API 403 shows the no-access state", async ({ page }) => {
  const engine = await mockEngine(page, { me: CHEN_ME });
  engine.statusOverrides[`GET /api/roster/${MATH201_ID}`] = 403;
  await page.goto(`/course/${MATH201_ID}/roster`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();
});

test("tabs are filtered by capabilities", async ({ page }) => {
  await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}`);
  const tabs = page.getByRole("navigation", { name: "Course" }).getByRole("link");
  await expect(tabs).toHaveText(["Content", "Attestations", "Sessions", "Badges", "Analytics"]);

  await mockEngine(page, { me: { ...CHEN_ME, capabilities: { course_list: { scope: "own", access: "full" } } } });
  await page.goto(`/course/${MATH201_ID}`);
  await expect(tabs).toHaveText(["Content"]);
});

test("AI panel creates a session with only course_id and sends CSRF on every non-GET", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}`);
  await expect(page.getByRole("heading", { name: "Your Mastery Progress" })).toBeVisible();

  await page.getByRole("button", { name: "Open AI assistant" }).click();
  await page.getByRole("textbox", { name: "Message the AI assistant" }).fill("What should I study next?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Here is your smoke-test answer.")).toBeVisible();

  const session = engine.requests.find((r) => r.method === "POST" && r.path === "/api/session");
  expect(session?.body).toEqual({ course_id: CS101_ID });
  const nonGet = engine.requests.filter((r) => r.method !== "GET");
  expect(nonGet.length).toBeGreaterThan(0);
  for (const r of nonGet) expect(r.headers["x-csrf-token"], `${r.method} ${r.path}`).toBe(SMOKE_CSRF);
  expect(engine.unhandled).toEqual([]);
});
