import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CS101_ID, EMMA_ME, TORRES_ME, mockEngine, setSessionCookies } from "./fake-api";

const PASSWORD = "correct horse battery staple";

async function expectNoSeriousA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test("unauthenticated visit redirects to /login with next", async ({ page }) => {
  await page.goto(`/course/${CS101_ID}/gradebook`);
  await expect(page).toHaveURL(`/login?next=${encodeURIComponent(`/course/${CS101_ID}/gradebook`)}`);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("login form is labelled, supports show-password and has no serious axe violations", async ({ page }) => {
  await mockEngine(page, { me: null });
  await page.goto("/login");

  const username = page.getByLabel("Username");
  const password = page.getByLabel("Password", { exact: true });
  await expect(username).toHaveAttribute("autocomplete", "username");
  await expect(password).toHaveAttribute("autocomplete", "current-password");
  await expect(password).toHaveAttribute("type", "password");

  const toggle = page.getByRole("button", { name: "Show password" });
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(page.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");

  await expectNoSeriousA11yViolations(page);
});

test("a 401 shows the generic error in a role=alert region", async ({ page }) => {
  const engine = await mockEngine(page, { me: null, accounts: { "emma.smith@student.edu": { password: PASSWORD, me: EMMA_ME } } });
  await page.goto("/login");

  await page.getByLabel("Username").fill("emma.smith@student.edu");
  await page.getByLabel("Password", { exact: true }).fill("wrong password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.locator("form").getByRole("alert")).toHaveText("Invalid username or password.");
  await expect(page).toHaveURL("/login");
  await expectNoSeriousA11yViolations(page);

  const login = engine.requests.find((r) => r.path === "/api/auth/login");
  expect(login?.body).toEqual({ username: "emma.smith@student.edu", password: "wrong password" });
});

test("successful login without next goes to the course list when home_route is not built yet", async ({ page, context, baseURL }) => {
  const engine = await mockEngine(page, {
    me: null,
    accounts: { "emma.smith@student.edu": { password: PASSWORD, me: EMMA_ME } },
    onLogin: () => setSessionCookies(context, baseURL!),
  });
  await page.goto("/login");

  await page.getByLabel("Username").fill("Emma.Smith@student.edu");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("link", { name: "CS 101 — Introduction to Computer Science" })).toBeVisible();
  await expect(page.getByRole("link", { name: "MATH 201 — Linear Algebra" })).toBeVisible();
  await expect(page.getByRole("link", { name: "BIO 150 — General Biology" })).toBeVisible();
  await expect(page.getByRole("link", { name: /ENG 102/ })).toHaveCount(0);
  expect(engine.unhandled).toEqual([]);
});

test("successful login honours ?next=", async ({ page, context, baseURL }) => {
  await mockEngine(page, {
    me: null,
    accounts: { "m.torres@university.edu": { password: PASSWORD, me: TORRES_ME } },
    onLogin: () => setSessionCookies(context, baseURL!),
  });
  await page.goto(`/login?next=${encodeURIComponent(`/course/${CS101_ID}/roster`)}`);

  await page.getByLabel("Username").fill("m.torres@university.edu");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(`/course/${CS101_ID}/roster`);
  await expect(page.getByRole("button", { name: /Account menu: Dr\. Maria Torres, Faculty/ })).toBeVisible();
});

test("an off-site ?next= is ignored", async ({ page, context, baseURL }) => {
  await mockEngine(page, {
    me: null,
    accounts: { "m.torres@university.edu": { password: PASSWORD, me: TORRES_ME } },
    onLogin: () => setSessionCookies(context, baseURL!),
  });
  await page.goto(`/login?next=${encodeURIComponent("//evil.example/steal")}`);

  await page.getByLabel("Username").fill("m.torres@university.edu");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL("/");
});

// searchParams.get decodes %09 to a tab, which URL parsing strips: "/\t/evil.example" -> "//evil.example".
for (const next of ["/\t/evil.example", "javascript:alert(1)", "https://evil.example"]) {
  test(`login ignores the off-site ?next=${JSON.stringify(next)}`, async ({ page, context, baseURL }) => {
    await mockEngine(page, {
      me: null,
      accounts: { "m.torres@university.edu": { password: PASSWORD, me: TORRES_ME } },
      onLogin: () => setSessionCookies(context, baseURL!),
    });
    await page.goto(`/login?next=${encodeURIComponent(next)}`);

    await page.getByLabel("Username").fill("m.torres@university.edu");
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(`${baseURL}/`);
  });
}

test("a 401 from /api/auth/me with a stale cookie sends the browser to /login?next=", async ({ page, context, baseURL }) => {
  await setSessionCookies(context, baseURL!);
  await mockEngine(page, { me: null });

  await page.goto(`/course/${CS101_ID}`);

  await expect(page).toHaveURL(`/login?next=${encodeURIComponent(`/course/${CS101_ID}`)}`);
});
