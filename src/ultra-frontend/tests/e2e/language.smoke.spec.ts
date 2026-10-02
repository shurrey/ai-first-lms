import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import {
  CREDENTIAL_RECOMMENDATION, CREDENTIAL_RECOMMENDATION_ID, CS101_ID, EMMA_ID, EMMA_ME, INSIGHTS_UPDATE_ID,
  TORRES_ME, corsHeaders, mockEngine, setSessionCookies,
} from "./fake-api";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

test.beforeEach(async ({ context, baseURL }) => {
  await setSessionCookies(context, baseURL!);
});

async function openPanelAndAsk(page: Page) {
  await page.goto(`/course/${CS101_ID}`);
  await expect(page.getByRole("heading", { name: "Your Mastery Progress" })).toBeVisible();
  await page.getByRole("button", { name: "Open AI assistant" }).click();
  await page.getByRole("textbox", { name: "Message the AI assistant" }).fill("What should I study next?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Here is your smoke-test answer.")).toBeVisible();
}

test("AI panel labels the speaker Tutor (AI) and uses no anthropomorphic copy", async ({ page }) => {
  await mockEngine(page, { me: EMMA_ME });
  await openPanelAndAsk(page);
  await expect(page.getByRole("complementary", { name: "AI assistant" }).getByText("Tutor (AI)").first()).toBeVisible();
  const panelText = await page.locator("body").innerText();
  expect(panelText).not.toMatch(/Thinking|companion|I'm your|AI Tutor/i);
});

test("AI panel shows Working… while a turn runs", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  // Hold the converse response so the in-progress state is observable.
  let release: () => void = () => {};
  const held = new Promise<void>((r) => { release = r; });
  await page.route("**/api/converse", async (route) => {
    await held;
    await route.fallback();
  });
  await page.goto(`/course/${CS101_ID}`);
  await page.getByRole("button", { name: "Open AI assistant" }).click();
  await page.getByRole("textbox", { name: "Message the AI assistant" }).fill("Hello");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Working…" })).toBeVisible();
  release();
  await expect(page.getByText("Here is your smoke-test answer.")).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("generated answers carry an AI-generated · sources label listing what ran", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  await openPanelAndAsk(page);
  const panel = page.getByRole("complementary", { name: "AI assistant" });
  const label = panel.getByRole("button", { name: "AI-generated · sources" });
  await expect(label).toHaveCount(1);
  await expect(label).toHaveAttribute("aria-expanded", "false");
  await label.click();
  await expect(label).toHaveAttribute("aria-expanded", "true");
  await expect(panel.getByText("Agent: tutor")).toBeVisible();
  await expect(panel.getByText("Tool: content.retrieve")).toBeVisible();

  const results = await new AxeBuilder({ page }).include("aside").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
  expect(engine.unhandled).toEqual([]);
});

test("learner insights label links to the profile_update that wrote them", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}`);
  await expect(page.getByText("You learn fastest from worked examples.")).toBeVisible();
  const label = page.getByRole("button", { name: "AI-generated · sources" });
  await expect(label).toHaveCount(1);
  await expect.poll(() => engine.requests.some((r) => r.path === "/api/ai-actions")).toBe(true);
  await label.click();
  await expect(page.getByText("Tutoring session, 28 Sep")).toBeVisible();
  expect(engine.requests.some((r) => r.path === `/api/ai-actions/${INSIGHTS_UPDATE_ID}`)).toBe(true);
  expect(engine.unhandled).toEqual([]);
});

test("a provenance record the viewer cannot see yet is reported as unavailable", async ({ page }) => {
  // The engine answers 404 to a learner for an unreleased or rejected draft.
  const engine = await mockEngine(page, { me: EMMA_ME });
  engine.statusOverrides[`GET /api/ai-actions/${INSIGHTS_UPDATE_ID}`] = 404;
  await page.goto(`/course/${CS101_ID}`);
  await expect(page.getByText("You learn fastest from worked examples.")).toBeVisible();
  await expect.poll(() => engine.requests.some((r) => r.path === "/api/ai-actions")).toBe(true);
  await page.getByRole("button", { name: "AI-generated · sources" }).click();
  await expect(page.getByTestId("ai-generated-label").getByRole("alert")).toHaveText(
    "This provenance record isn't available to you."
  );
  expect(engine.unhandled).toEqual([]);
});

/** Replaces the fake list response; registered after mockEngine, so it takes precedence. */
async function listAiActionsReturns(page: Page, items: unknown[]) {
  await page.route((url) => url.pathname === "/api/ai-actions", (route) => route.request().method() === "GET"
    ? route.fulfill({ status: 200, contentType: "application/json", headers: corsHeaders(route.request()), body: JSON.stringify({ items, next_cursor: null }) })
    : route.fallback());
}

const pendingRow = (page: Page) => page.locator("div.rounded-xl", { hasText: "Emma Smith" });

test("pending badge recommendation label links to its provenance", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  const lookup = page.waitForRequest((r) => r.url().includes("/api/ai-actions?"));
  await page.goto(`/course/${CS101_ID}/credentials`);
  const query = new URL((await lookup).url()).searchParams;
  expect(query.get("course_id")).toBe(CS101_ID);
  expect(query.get("subject_person_id")).toBe(EMMA_ID);
  expect(query.get("action_type")).toBe("recommendation");

  const row = pendingRow(page);
  await expect(row.getByText("Python Fundamentals")).toBeVisible();
  await row.getByRole("button", { name: "AI-generated · sources" }).click();
  await expect(row.getByText("Type Conversion attestation")).toBeVisible();
  expect(engine.requests.some((r) => r.path === `/api/ai-actions/${CREDENTIAL_RECOMMENDATION_ID}`)).toBe(true);
  expect(engine.unhandled).toEqual([]);
});

test("seed-style badge recommendation matches by person and microcredential", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await listAiActionsReturns(page, [{ ...CREDENTIAL_RECOMMENDATION, target_type: null, target_id: null }]);
  await page.goto(`/course/${CS101_ID}/credentials`);
  await pendingRow(page).getByRole("button", { name: "AI-generated · sources" }).click();
  await expect(pendingRow(page).getByText("Type Conversion attestation")).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("badge recommendation label falls back when no provenance record matches", async ({ page }) => {
  await mockEngine(page, { me: TORRES_ME });
  await listAiActionsReturns(page, []);
  await page.goto(`/course/${CS101_ID}/credentials`);
  await pendingRow(page).getByRole("button", { name: "AI-generated · sources" }).click();
  await expect(pendingRow(page).getByText(/No provenance record is linked/)).toBeVisible();
});

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? tsxFiles(p) : p.endsWith(".tsx") ? [p] : [];
  });
}

test("no banned anthropomorphic strings in shipped UI source", () => {
  const banned = /\b(Thinking|companion|buddy)\b|AI Tutor|I'm happy to|I feel/;
  const hits = ["app", "components"].flatMap((d) => tsxFiles(join(__dirname, "..", "..", d)))
    .flatMap((f) => readFileSync(f, "utf8").split("\n").map((line, i) => ({ f, i, line })))
    .filter(({ line }) => banned.test(line))
    .map(({ f, i, line }) => `${f}:${i + 1}: ${line.trim()}`);
  expect(hits).toEqual([]);
});
