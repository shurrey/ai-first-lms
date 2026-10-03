import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import {
  ADMIN_ME, CHEN_ME, CS101_ID, EMMA_ME, MATH201_ID, SMOKE_AI_ACTION_ID, TORRES_ME, corsHeaders, mockEngine, setSessionCookies,
} from "./fake-api";

test.beforeEach(async ({ context, baseURL }) => {
  await setSessionCookies(context, baseURL!);
});

async function expectNoSeriousAxe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

const tabs = (page: Page) => page.getByRole("navigation", { name: "Course" }).getByRole("link");

test("faculty AI Review tab renders the course measures from a contract-shaped payload", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}`);
  await expect(tabs(page).filter({ hasText: "AI Review" })).toHaveCount(1);

  await tabs(page).filter({ hasText: "AI Review" }).click();
  await expect(page).toHaveURL(new RegExp(`/course/${CS101_ID}/ai-review$`));
  await expect(page.getByRole("heading", { name: "AI Review", exact: true })).toBeVisible();

  const rates = page.getByRole("table", { name: /Decision counts and rates by agent and action type/ });
  await expect(rates.getByRole("row", { name: /grader/ })).toContainText("grade draft");
  await expect(rates.getByRole("row", { name: /grader/ })).toContainText("55%");
  await expect(rates.getByRole("row", { name: /tutor/ })).toContainText("criterion feedback");

  // 11 accepted of 19 decided across both rows.
  await expect(page.locator("dt", { hasText: /^Acceptance rate$/ }).locator("..")).toContainText("58%");

  const changes = page.getByRole("table", { name: /Mean change instructors made/ });
  await expect(changes.getByRole("row", { name: /thesis/ })).toContainText("+0.75 (raised)");
  await expect(changes.getByRole("row", { name: /evidence use/ })).toContainText("−0.50 (lowered)");

  const learning = page.getByRole("table", { name: /after accepted, edited or rejected feedback/ });
  await expect(learning.getByRole("row", { name: /edited/i })).toContainText("+0.90 (raised)");
  await expect(learning.getByRole("row", { name: /rejected/i })).toContainText("n/a");

  const mostEdited = page.getByRole("table", { name: /ranked by how often/ });
  await expect(mostEdited.getByRole("row").nth(1)).toContainText("thesis");

  await expect(page.locator("dt", { hasText: "Hint-dependency ratio" }).locator("..")).toContainText("0.25 hints per attempt");
  const practice = page.getByRole("region", { name: "Practice sets" });
  await expect(practice.locator("dt", { hasText: "Started" }).locator("..")).toContainText("3");
  await expect(practice).toContainText("Counts only.");

  await expect(page.getByRole("img", { name: /grader · grade draft: 6 accepted, 4 edited, 1 rejected/ })).toBeVisible();

  const recent = page.getByRole("table", { name: /most recent generated items/ });
  await expect(recent.getByRole("row", { name: /grader/ })).toContainText("none yet");
  await recent.getByRole("button", { name: "AI-generated · sources" }).click();
  await expect(recent.getByText("Essay rubric")).toBeVisible();
  await expect(recent.getByText(/grading\.release_mode/)).toBeVisible();
  expect(engine.requests.some((r) => r.path === `/api/ai-actions/${SMOKE_AI_ACTION_ID}`)).toBe(true);

  await expectNoSeriousAxe(page);
  expect(engine.unhandled).toEqual([]);
});

test("AI Review date range is sent as from/to with an exclusive end", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}/ai-review`);
  await expect(page.getByRole("table", { name: /by agent and action type/ })).toBeVisible();

  await page.getByLabel("From").fill("2026-09-01");
  await page.getByLabel("To (inclusive)").fill("2026-09-30");
  const request = page.waitForRequest((r) => r.url().includes(`/api/measurement/courses/${CS101_ID}?`));
  await page.getByRole("button", { name: "Apply" }).click();
  const url = new URL((await request).url());
  expect(url.searchParams.get("from")).toBe("2026-09-01T00:00:00.000Z");
  expect(url.searchParams.get("to")).toBe("2026-10-01T00:00:00.000Z");
  expect(engine.unhandled).toEqual([]);
});

test("AI Review export downloads JSON and CSV", async ({ page }) => {
  await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}/ai-review`);

  const [json] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "JSON (all tables)" }).click(),
  ]);
  expect(json.suggestedFilename()).toBe("measurement.json");

  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "CSV: decisions" }).click(),
  ]);
  expect(csv.suggestedFilename()).toBe("human_decisions.csv");
  await expect(page.getByRole("status").filter({ hasText: "Downloaded human_decisions.csv." })).toBeVisible();
});

test("AI Review export falls back to a local filename when Content-Disposition is not exposed", async ({ page }) => {
  await mockEngine(page, { me: TORRES_ME });
  await page.route((url) => url.pathname === "/api/measurement/export", (route) => route.request().method() === "GET"
    ? route.fulfill({
      status: 200,
      contentType: "text/csv",
      headers: { ...corsHeaders(route.request()), "content-disposition": 'attachment; filename="human_decisions.csv"' },
      body: "id,decision\n",
    })
    : route.fallback());
  await page.goto(`/course/${CS101_ID}/ai-review`);
  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "CSV: decisions" }).click(),
  ]);
  expect(csv.suggestedFilename()).toBe("ai-review-human_decisions.csv");
});

test("AI Review tab is hidden without the capability", async ({ page }) => {
  await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}`);
  await expect(tabs(page)).toHaveText(["Content", "Assignments", "Attestations", "Sessions", "Badges", "Analytics"]);

  await page.goto(`/course/${CS101_ID}/ai-review`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();
});

test("AI Review tab is hidden for a faculty grant on a course the person does not teach", async ({ page }) => {
  const engine = await mockEngine(page, {
    me: { ...CHEN_ME, enrollments: [...CHEN_ME.enrollments, { course_id: CS101_ID, slug: "cs101", title: "CS 101", role: "student" }] },
  });
  await page.goto(`/course/${MATH201_ID}`);
  await expect(tabs(page).filter({ hasText: "AI Review" })).toHaveCount(1);
  await page.goto(`/course/${CS101_ID}`);
  await expect(tabs(page).filter({ hasText: "Content" })).toHaveCount(1);
  await expect(tabs(page).filter({ hasText: "AI Review" })).toHaveCount(0);
  expect(engine.requests.some((r) => r.path.startsWith("/api/measurement"))).toBe(false);
});

test("admin sees the institution rollup under the Institution scope", async ({ page }) => {
  const engine = await mockEngine(page, { me: ADMIN_ME });
  await page.goto("/course/all");
  await tabs(page).filter({ hasText: "AI Review" }).click();
  await expect(page.getByRole("heading", { name: "AI Review — institution" })).toBeVisible();
  await expect(page.getByText("No recorded mismatches between applied and effective policy.")).toBeVisible();
  await expect(page.getByRole("table", { name: "Decision counts and rates per course" }).getByRole("row", { name: /CS 101/ })).toContainText("58%");
  await expectNoSeriousAxe(page);
  expect(engine.unhandled).toEqual([]);
});
