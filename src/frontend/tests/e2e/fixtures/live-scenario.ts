import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Scenario specs replay src/platform/scenarios/<id>-*.yaml through the UI with the same
 * user and message as `scripts/demo`, so one set of recorded LLM fixtures serves both.
 */
const SCENARIOS_DIR = path.resolve(__dirname, "../../../../platform/scenarios");

/** A live turn can take minutes against the real API; replay finishes in seconds. */
export const TURN_TIMEOUT_MS = 150_000;

const ROLE_LABELS: Record<string, string> = {
  student: "Student",
  faculty: "Faculty",
  program_lead: "Program Lead",
  advisor: "Advisor",
  admin: "Admin",
};

export interface LiveScenario {
  id: number;
  loginAs: string;
  activeRole: string | null;
  courseSlug: string;
  /** Only the first user turn; every Chat UI scenario spec is single-turn. */
  message: string;
  approvals: number;
  xfail: string | null;
}

function field(text: string, name: string): string | null {
  const match = new RegExp(`^\\s*-?\\s*${name}:\\s*"?(.*?)"?\\s*$`, "m").exec(text);
  return match ? match[1] : null;
}

/** Reads the handful of flat fields the specs need; throws when a required one is missing. */
export function loadScenario(id: number): LiveScenario {
  const prefix = `${String(id).padStart(2, "0")}-`;
  const file = readdirSync(SCENARIOS_DIR).find((f) => f.startsWith(prefix) && f.endsWith(".yaml"));
  if (!file) throw new Error(`No scenario ${id} in ${SCENARIOS_DIR}`);
  const text = readFileSync(path.join(SCENARIOS_DIR, file), "utf8");
  const required = (name: string) => {
    const value = field(text, name);
    if (!value) throw new Error(`${file} has no ${name}`);
    return value;
  };
  return {
    id,
    loginAs: required("login_as"),
    activeRole: field(text, "active_role"),
    courseSlug: required("course_id"),
    message: required("message"),
    approvals: (text.match(/^\s*-\s*decision:\s*approve\s*$/gm) ?? []).length,
    xfail: field(text, "xfail"),
  };
}

/** "cs101" -> /^CS 101\b/, matching the course picker's option titles. */
function courseTitlePattern(slug: string): RegExp {
  const match = /^([a-z]+)(\d+)$/i.exec(slug);
  if (!match) throw new Error(`Unexpected course slug ${slug}`);
  return new RegExp(`^${match[1].toUpperCase()} ${match[2]}\\b`);
}

export async function expectActiveRole(page: Page, role: string | null) {
  if (!role) return;
  await expect(page.getByTestId("account-menu-button")).toContainText(ROLE_LABELS[role] ?? role);
}

/** Picks the course in the header and waits for the orchestrator to create the session. */
export async function startCourseSession(page: Page, slug: string) {
  const select = page.locator("#course-select");
  await expect(select).toBeVisible();
  const pattern = courseTitlePattern(slug);
  const options = select.locator("option");
  const labels = await options.allTextContents();
  const index = labels.findIndex((l) => pattern.test(l));
  if (index < 0) throw new Error(`No course matching ${pattern} in [${labels.join(", ")}]`);
  const value = await options.nth(index).getAttribute("value");
  if (!value) throw new Error(`Course option ${labels[index]} has no value`);
  const created = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/session" && r.request().method() === "POST"
  );
  await select.selectOption(value);
  expect((await created).ok()).toBe(true);
  await expect(page.getByPlaceholder(/Type a message/)).toBeEnabled();
  // Every new session streams a generated brief first; the input stays busy until it lands.
  await expect(answerLabels(page).first().or(turnError(page))).toBeVisible({ timeout: TURN_TIMEOUT_MS });
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible({ timeout: TURN_TIMEOUT_MS });
}

export function approvalGate(page: Page): Locator {
  return page.getByRole("region", { name: "Approval needed" });
}

/** Provenance labels in the message list; the approval preview's label sits outside it. */
function answerLabels(page: Page): Locator {
  return page.locator("main > div").first().getByTestId("ai-generated-label");
}

function turnError(page: Page): Locator {
  return page.locator("main").getByText(/^(Error: |Failed to send message)/).first();
}

export interface TurnObservations {
  /** The action text of each approval gate, in the order they were approved. */
  approvedActions: string[];
}

/**
 * Sends `message`, approves `approvals` gates as they appear, and waits for the final answer.
 * Fails on an error answer or when fewer gates appear than expected.
 */
export async function runTurn(page: Page, message: string, approvals: number): Promise<TurnObservations> {
  const labelsBefore = await answerLabels(page).count();
  await page.getByPlaceholder(/Type a message/).fill(message);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(message, { exact: true }).first()).toBeVisible();

  const approvedActions: string[] = [];
  for (let i = 0; i < approvals; i++) {
    const gate = approvalGate(page);
    await expect(gate.or(turnError(page))).toBeVisible({ timeout: TURN_TIMEOUT_MS });
    await expect(turnError(page), `turn failed before approval ${i + 1}`).toHaveCount(0);
    // The previous gate stays rendered, disabled, until its decision lands; an enabled
    // button therefore belongs to the next gate.
    const approve = gate.getByRole("button", { name: "Approve" });
    await expect(approve).toBeEnabled({ timeout: TURN_TIMEOUT_MS });
    await expect(gate.getByText("Awaiting Approval")).toBeVisible();
    approvedActions.push((await gate.locator("p.text-sm.font-medium").last().textContent()) ?? "");
    const decided = page.waitForResponse(
      (r) => new URL(r.url()).pathname === "/api/approval" && r.request().method() === "POST"
    );
    await approve.click();
    expect((await decided).ok()).toBe(true);
  }

  await expect(answerLabels(page).nth(labelsBefore).or(turnError(page))).toBeVisible({ timeout: TURN_TIMEOUT_MS });
  await expect(turnError(page)).toHaveCount(0);
  await expect(approvalGate(page)).toHaveCount(0);
  return { approvedActions };
}

/** The collapsed "What ran" drawer lists every tool call the turn made. */
export async function toolCallsRun(page: Page): Promise<string[]> {
  const drawer = page.getByRole("button", { name: /What ran/ }).last();
  await expect(drawer).toBeVisible();
  if ((await drawer.getAttribute("aria-expanded")) !== "true") await drawer.click();
  const tools = drawer.locator("xpath=..").locator("div:has(> span[role=img]) > span:nth-child(2)");
  return (await tools.allTextContents()).map((t) => t.trim());
}
