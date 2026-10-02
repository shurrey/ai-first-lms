import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { CS101_ID, HAYES, TORRES, TORRES_AS_PROGRAM_LEAD, api, fulfill, type FakeMe } from "./fixtures/fake-api";
import { selectCourse, setupMockAPI } from "./fixtures/setup";
import { scenario1Events, scenario11Events } from "./fixtures/mock-events";

const SESSION_ID = "lp-session";
const TURN_ID = "lp-turn";
const AI_ACTION_ID = "9f1d2c3b-4a5e-4f60-8a7b-1c2d3e4f5a6b";

const TORRES_AI_REVIEW: FakeMe = {
  ...TORRES,
  capabilities: {
    ...TORRES.capabilities,
    ai_review: { scope: "own", access: "read" },
    ai_actions_log: { scope: "own", access: "read" },
  },
};

const HAYES_AI_REVIEW: FakeMe = {
  ...HAYES,
  capabilities: { ...HAYES.capabilities, ai_review: { scope: "all", access: "read" } },
};

const SUMMARY = {
  scope: { type: "course", id: CS101_ID, title: "CS 101 — Intro to Computer Science" },
  from: "2026-09-01T00:00:00Z",
  to: "2026-10-01T00:00:00Z",
  rates: [
    {
      agent: "grading_assistant", action_type: "grade_draft", total: 20, accepted: 12, edited: 6,
      rejected: 1, other: 0, undecided: 1, acceptance_rate: 0.6316, edit_rate: 0.3158, reject_rate: 0.0526,
    },
    {
      agent: "tutor", action_type: "practice_item", total: 8, accepted: 5, edited: 0,
      rejected: 0, other: 2, undecided: 1, acceptance_rate: 0.7143, edit_rate: 0, reject_rate: 0,
    },
  ],
  criterion_score_changes: [
    { criterion_id: "c0000000-0000-4000-8000-000000000001", criterion_key: "thesis", n: 5, mean_delta: -0.8 },
  ],
  learning_delta_by_decision: {
    accepted: { n: 9, mean_delta: 0.42 },
    edited: { n: 4, mean_delta: 0.3 },
    rejected: { n: 1, mean_delta: null },
  },
  most_edited_criteria: [
    { criterion_id: "c0000000-0000-4000-8000-000000000001", criterion_key: "thesis", edit_count: 5, edit_rate: 0.25 },
  ],
  offloading: { hint_dependency_ratio: 0.2, solution_check_trips: 3 },
};

const ROLLUP = {
  ...SUMMARY,
  scope: { type: "institution", id: null, title: null },
  per_course: [
    {
      course: { course_id: CS101_ID, slug: "cs101", title: "CS 101 — Intro to Computer Science" },
      totals: {
        total: 28, accepted: 17, edited: 6, rejected: 1, other: 2, undecided: 2,
        acceptance_rate: 0.654, edit_rate: 0.231, reject_rate: 0.038,
      },
    },
  ],
  compliance: { mismatches_count: 2 },
};

const AI_ACTION = {
  id: AI_ACTION_ID,
  session_id: SESSION_ID,
  turn_id: TURN_ID,
  agent: "tutor",
  action_type: "generation",
  sources: [{ type: "content_item", id: "ci-1", version: 3, title: "Recursion lecture notes" }],
  policies: [{ key: "tutor.answer_mode", value: "hints_only", scope_type: "course", scope_id: CS101_ID, version: 1 }],
  model: "claude-test",
  output: {},
  created_at: "2026-10-01T12:00:00Z",
  decisions: [],
};

/** scenario-1 with the tutor citing a source; the final event optionally names an ai_action. */
function citedTurn(aiActionIds?: string[]) {
  return scenario1Events(SESSION_ID, TURN_ID).map((e) => {
    if (e.event === "agent_result") return { ...e, payload: { ...e.payload, output: { citations: ["Recursion lecture notes"] } } };
    if (e.event === "final" && aiActionIds) return { ...e, payload: { ...e.payload, ai_action_ids: aiActionIds } };
    return e;
  });
}

async function expectNoSeriousAxe(page: Page, ...selectors: string[]) {
  let builder = new AxeBuilder({ page });
  for (const sel of selectors) builder = builder.include(sel);
  const results = await builder.analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

async function ask(page: Page, text = "Explain recursion") {
  await page.getByPlaceholder(/Type a message/).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test.describe("Language: tools, not beings", () => {
  test("streaming status reads Working… before any tool has run", async ({ page }) => {
    const [reasoning] = scenario1Events(SESSION_ID, TURN_ID);
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: [reasoning] });
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    await expect(page.getByRole("status").filter({ hasText: "Working…" })).toBeVisible();
  });

  test("streaming status reads Running: <tool> once a tool has run", async ({ page }) => {
    const [reasoning, , , toolCall] = scenario1Events(SESSION_ID, TURN_ID);
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: [reasoning, { ...toolCall, sequence: 2 }] });
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    await expect(page.getByRole("status").filter({ hasText: "Running: content.retrieve" })).toBeVisible();
  });

  test("the activity drawer is labelled What ran", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: scenario1Events(SESSION_ID, TURN_ID) });
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    const drawer = page.getByRole("button", { name: /What ran/ });
    await expect(drawer).toBeVisible({ timeout: 10000 });
    await expect(drawer).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText(/Thinking/)).toHaveCount(0);
    await drawer.click();
    await expect(drawer).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("img", { name: "succeeded" }).first()).toBeVisible();
    await expectNoSeriousAxe(page, "main");
  });

  test("no banned UI terms in .tsx string literals", () => {
    const root = join(__dirname, "..", "..");
    const banned = /\b(Thinking|companion|buddy|AI Tutor)\b/;
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        if (name === "node_modules" || name.startsWith(".")) continue;
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (path.endsWith(".tsx")) {
          readFileSync(path, "utf8").split("\n").forEach((line, i) => {
            const trimmed = line.trim();
            if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("{/*")) return;
            if (banned.test(line)) offenders.push(`${path}:${i + 1}: ${trimmed}`);
          });
        }
      }
    };
    for (const dir of ["app", "components"]) walk(join(root, dir));
    expect(offenders).toEqual([]);
  });
});

test.describe("AI-generated · sources label", () => {
  test("without ai_action ids it lists what the turn reported", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: citedTurn() });
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    const label = page.getByRole("button", { name: "AI-generated · sources" });
    await expect(label).toBeVisible({ timeout: 10000 });
    await label.click();
    await expect(label).toHaveAttribute("aria-expanded", "true");
    const panel = page.getByTestId("ai-generated-label");
    await expect(panel.getByText("content.retrieve")).toBeVisible();
    await expect(panel.getByText("Recursion lecture notes")).toBeVisible();
    await expectNoSeriousAxe(page, "main");
  });

  test("with ai_action ids it loads provenance from GET /api/ai-actions/{id}", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES_AI_REVIEW, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: citedTurn([AI_ACTION_ID]) });
    await page.route(api(`/api/ai-actions/${AI_ACTION_ID}`), (route) => fulfill(route, 200, AI_ACTION));
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    const req = page.waitForRequest((r) => r.url() === api(`/api/ai-actions/${AI_ACTION_ID}`) && r.method() === "GET");
    await page.getByRole("button", { name: "AI-generated · sources" }).click();
    await req;
    const panel = page.getByTestId("ai-generated-label");
    await expect(panel.getByText("Recursion lecture notes")).toBeVisible();
    await expect(panel.getByText(/tutor\.answer_mode/)).toBeVisible();
  });

  test("a provenance record the viewer cannot see yet is reported as unavailable", async ({ page }) => {
    // The engine answers 404 to a learner for an unreleased or rejected draft.
    await setupMockAPI(page, { me: TORRES_AI_REVIEW, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: citedTurn([AI_ACTION_ID]) });
    await page.route(api(`/api/ai-actions/${AI_ACTION_ID}`), (route) => fulfill(route, 404, { detail: "Not found" }));
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    await page.getByRole("button", { name: "AI-generated · sources" }).click();
    await expect(page.getByTestId("ai-generated-label").getByRole("alert")).toHaveText(
      "This provenance record isn't available to you."
    );
  });

  test("final artifacts render as canvases with the label", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: scenario11Events(SESSION_ID, TURN_ID) });
    await page.goto("/");
    await selectCourse(page);
    await ask(page);
    await expect(page.getByRole("heading", { name: "Writing Improvement Path" })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: "AI-generated · sources" })).toHaveCount(2);
    await expect(page.getByText("Generated", { exact: true }).first()).toBeVisible();
    await expectNoSeriousAxe(page, '[data-testid="canvas-shell"]', '[data-testid="ai-generated-label"]');
  });
});

test.describe("MeasurementCanvas", () => {
  test("faculty opens AI Review from the CoursePanel and sees the course measures", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES_AI_REVIEW, sessionId: SESSION_ID, turnId: TURN_ID });
    await page.route(api(`/api/measurement/courses/${CS101_ID}`), (route) => fulfill(route, 200, SUMMARY));
    await page.goto("/");
    await selectCourse(page);
    await page.getByRole("button", { name: "Open AI Review" }).click();

    const dialog = page.getByRole("dialog", { name: "AI Review" });
    await expect(dialog).toBeVisible();
    const rates = dialog.getByRole("table", { name: /Acceptance, edit and reject rates/ });
    await expect(rates.getByRole("row", { name: /grading assistant · grade draft/ })).toContainText("63%");
    await expect(rates.getByRole("row", { name: /grading assistant · grade draft/ })).toContainText("32%");
    await expect(dialog.getByRole("table", { name: /criterion scores/ })).toContainText("-0.8");
    await expect(dialog.getByRole("table", { name: /Learning change/ }).getByRole("row", { name: /Accepted/ })).toContainText("+0.42");
    await expect(dialog.getByRole("table", { name: /edited most often/ })).toContainText("thesis");
    await expect(dialog.getByRole("img", { name: /Decisions by agent/ })).toHaveAttribute("aria-label", /12 accepted, 6 edited, 1 rejected/);
    await expect(dialog.getByRole("radiogroup", { name: "Scope" })).toHaveCount(0);

    const exportJson = dialog.getByRole("link", { name: "Export all tables (JSON)" });
    await expect(exportJson).toHaveAttribute("href", api(`/api/measurement/export?course_id=${CS101_ID}&format=json`));
    await expect(dialog.getByRole("link", { name: "Export human decisions (CSV)" })).toHaveAttribute(
      "href",
      api(`/api/measurement/export?course_id=${CS101_ID}&format=csv&table=human_decisions`)
    );

    const results = await new AxeBuilder({ page }).include("dialog").analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
  });

  test("hidden without the ai_review capability", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID });
    await page.goto("/");
    await selectCourse(page);
    await expect(page.getByRole("button", { name: "Open AI Review" })).toHaveCount(0);
  });

  test("admin sees the institution rollup with per-course totals and compliance", async ({ page }) => {
    await setupMockAPI(page, { me: HAYES_AI_REVIEW, sessionId: SESSION_ID, turnId: TURN_ID });
    await page.route(api("/api/measurement/rollup"), (route) => fulfill(route, 200, ROLLUP));
    await page.goto("/");
    await selectCourse(page);
    await page.getByRole("button", { name: "Open AI Review" }).click();
    const dialog = page.getByRole("dialog", { name: "AI Review" });
    await expect(dialog.getByRole("table", { name: "Decisions by course" })).toContainText("CS 101");
    await expect(dialog.getByText("2 mismatches between recorded and effective policy.")).toBeVisible();

    const results = await new AxeBuilder({ page }).include("dialog").analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });

  test("the scope switch is a native radio group that follows arrow keys", async ({ page }) => {
    const lead: FakeMe = {
      ...TORRES_AS_PROGRAM_LEAD,
      capabilities: { ...TORRES_AS_PROGRAM_LEAD.capabilities, ai_review: { scope: "program", access: "read" } },
    };
    await setupMockAPI(page, { me: lead, sessionId: SESSION_ID, turnId: TURN_ID });
    await page.route(api(`/api/measurement/courses/${CS101_ID}`), (route) => fulfill(route, 200, SUMMARY));
    await page.goto("/");
    await selectCourse(page);
    await page.getByRole("button", { name: "Open AI Review" }).click();
    const scope = page.getByRole("dialog", { name: "AI Review" }).getByRole("radiogroup", { name: "Scope" });
    const course = scope.getByRole("radio", { name: "This course" });
    await expect(course).toBeChecked();
    await course.focus();
    await page.keyboard.press("ArrowRight");
    await expect(scope.getByRole("radio", { name: "Program" })).toBeChecked();
    await expect(scope.getByRole("radio", { name: "Program" })).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(course).toBeChecked();
  });

  test("a 403 from the measurement endpoint is reported, not blank", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES_AI_REVIEW, sessionId: SESSION_ID, turnId: TURN_ID });
    await page.route(api(`/api/measurement/courses/${CS101_ID}`), (route) => fulfill(route, 403, { detail: "Forbidden" }));
    await page.goto("/");
    await selectCourse(page);
    await page.getByRole("button", { name: "Open AI Review" }).click();
    await expect(page.getByRole("dialog").getByRole("alert")).toHaveText("Your role can't view AI Review for this course.");
  });
});
