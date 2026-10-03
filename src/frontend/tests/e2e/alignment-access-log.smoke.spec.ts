import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { CS101_ID, EMMA, HAYES, TORRES, api, fulfill, type FakeMe } from "./fixtures/fake-api";
import { selectCourse, setupMockAPI } from "./fixtures/setup";

const SESSION_ID = "al-session";
const TURN_ID = "al-turn";

async function expectNoSeriousAxe(page: Page, selector: string) {
  const results = await new AxeBuilder({ page }).include(selector).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

function envelope(event: string, sequence: number, payload: unknown) {
  return { event, session_id: SESSION_ID, turn_id: TURN_ID, sequence, timestamp: new Date().toISOString(), payload };
}

const LEVELS = [
  { score: 1, label: "Beginning", descriptor: "No clear claim." },
  { score: 2, label: "Developing", descriptor: "Claim is vague." },
  { score: 3, label: "Proficient", descriptor: "Claim is specific and arguable." },
];

const PROPOSAL_TURN = [
  envelope("final", 1, {
    answer_markdown: "Here are proposed criteria aligned to the ENG 102 outcomes.",
    artifacts: [
      {
        artifact_id: "draft-1",
        type: "content_draft",
        data: {
          title: "Alignment proposal: Essay 2",
          kind: "alignment_proposal",
          assignment_node: "node-essay-2",
          outcomes: [
            { node_id: "o-1", title: "Construct an arguable thesis", reason: "Syllabus week 2 focuses on thesis statements." },
            { node_id: "o-2", title: "Integrate cited evidence", reason: "The prompt asks for two sources." },
            { node_id: "o-3", title: "Revise for audience", reason: "The essay has a revision step." },
          ],
          criteria: [
            { key: "thesis", description: "States a clear, arguable thesis.", levels: LEVELS, outcome_nodes: ["o-1"] },
            { key: "evidence", description: "Uses evidence.", levels: LEVELS, outcome_nodes: ["o-2"] },
            { key: "style", description: "Uses varied sentences.", levels: LEVELS, outcome_nodes: [] },
          ],
        },
      },
    ],
    ai_action_ids: [],
    cost_usd: 0.01,
    tokens: 100,
    wall_time_ms: 900,
  }),
];

test.describe("RubricCanvas: proposed criteria", () => {
  test("faculty accept, edit and reject each proposed criterion and save them to the alignment endpoint", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: PROPOSAL_TURN });
    const posted: Array<{ body: unknown; csrf: string | undefined }> = [];
    await page.route(api("/api/assignments/node-essay-2/alignment/decisions"), (route) => {
      posted.push({ body: route.request().postDataJSON(), csrf: route.request().headers()["x-csrf-token"] });
      return fulfill(route, 201, { ai_action_id: "aa-1", rubric_id: "r-1", criterion_ids: ["c-1", "c-2"], decisions: [] });
    });
    const messages: string[] = [];
    await page.route(api("/api/converse"), (route) => {
      if (route.request().method() === "POST") messages.push((route.request().postDataJSON() as { message: string }).message);
      return fulfill(route, 202, { turn_id: TURN_ID, stream_url: `/api/stream?session_id=${SESSION_ID}&turn_id=${TURN_ID}` });
    });
    await page.goto("/");
    await selectCourse(page);
    await page.getByPlaceholder(/Type a message/).fill("Propose rubric criteria for the essay");
    await page.getByRole("button", { name: "Send" }).click();

    const proposals = page.getByTestId("rubric-proposals").first();
    await expect(proposals.getByText("Aligned outcomes: Construct an arguable thesis")).toBeVisible({ timeout: 10000 });
    await expect(proposals.getByText("Why: Syllabus week 2 focuses on thesis statements.")).toBeVisible();
    await expect(proposals.getByRole("checkbox", { name: /^Accept/ })).toHaveCount(0);

    const evidence = proposals.getByRole("group", { name: "Decision for Evidence" });
    await evidence.getByRole("radio", { name: "Edit" }).check();
    await proposals.getByLabel("Evidence description").fill("Supports each claim with cited evidence.");
    await proposals.getByLabel("Evidence level 2 (Developing)").fill("Some claims cite evidence.");
    await proposals.getByRole("group", { name: "Evidence aligned outcomes" }).getByRole("checkbox", { name: "Revise for audience" }).check();
    await proposals.getByRole("group", { name: "Decision for Style" }).getByRole("radio", { name: "Reject" }).check();
    await proposals.getByLabel("Why reject Style? (optional)").fill("Not assessed here.");
    await expectNoSeriousAxe(page, '[data-testid="rubric-proposals"]');

    await proposals.getByRole("button", { name: "Send decisions" }).click();
    await expect(proposals.getByText("Decisions saved. Accepted and edited criteria are on the rubric.")).toBeVisible();
    expect(posted).toHaveLength(1);
    expect(posted[0].csrf).toBeTruthy();
    expect(posted[0].body).toEqual({
      decisions: [
        { key: "thesis", decision: "accept" },
        {
          key: "evidence",
          decision: "edit",
          criterion: {
            key: "evidence",
            description: "Supports each claim with cited evidence.",
            levels: LEVELS.map((l) => (l.score === 2 ? { ...l, descriptor: "Some claims cite evidence." } : l)),
            outcome_nodes: ["o-2", "o-3"],
          },
        },
        { key: "style", decision: "reject", reason: "Not assessed here." },
      ],
    });
    expect(messages).toHaveLength(1);
  });

  test("a refused save is reported and can be sent again", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: PROPOSAL_TURN });
    let calls = 0;
    await page.route(api("/api/assignments/node-essay-2/alignment/decisions"), (route) => {
      calls += 1;
      return calls === 1
        ? fulfill(route, 409, { detail: "A criterion already has scores." })
        : fulfill(route, 201, { ai_action_id: "aa-1", rubric_id: null, criterion_ids: [], decisions: [] });
    });
    await page.goto("/");
    await selectCourse(page);
    await page.getByPlaceholder(/Type a message/).fill("Propose rubric criteria for the essay");
    await page.getByRole("button", { name: "Send" }).click();
    const proposals = page.getByTestId("rubric-proposals").first();
    await proposals.getByRole("button", { name: "Send decisions" }).click({ timeout: 10000 });
    await expect(proposals.getByText(/Couldn't save your decisions/)).toBeVisible();
    await proposals.getByRole("button", { name: "Send decisions" }).click();
    await expect(proposals.getByText("Decisions saved. The rubric is unchanged.")).toBeVisible();
  });

  test("non-faculty viewers see the proposal without decision controls", async ({ page }) => {
    await setupMockAPI(page, { me: HAYES_IN_COURSE, sessionId: SESSION_ID, turnId: TURN_ID, sseEvents: PROPOSAL_TURN });
    let posted = false;
    await page.route(api("/api/assignments/node-essay-2/alignment/decisions"), (route) => {
      posted = true;
      return fulfill(route, 403, { detail: "Forbidden" });
    });
    await page.goto("/");
    await selectCourse(page, 2);
    await page.getByPlaceholder(/Type a message/).fill("Propose rubric criteria for the essay");
    await page.getByRole("button", { name: "Send" }).click();
    const proposals = page.getByTestId("rubric-proposals").first();
    await expect(proposals.getByText("Aligned outcomes: Construct an arguable thesis")).toBeVisible({ timeout: 10000 });
    await expect(proposals.getByRole("radio", { name: "Accept" }).first()).toBeDisabled();
    await expect(proposals.getByRole("button", { name: "Send decisions" })).toHaveCount(0);
    expect(posted).toBe(false);
  });
});

const HAYES_IN_COURSE: FakeMe = {
  ...HAYES,
  enrollments: [{ course_id: CS101_ID, slug: "cs101", title: "CS 101 — Intro to Computer Science", role: "observer" }],
};

const LOG_PAGE_1 = {
  entries: [
    { id: "l-1", actor: { id: "7a1c0000-0000-4000-8000-000000000001", display_name: "Dr. Maria Torres" }, subject_id: EMMA.person.id, resource: "analyst_summary", resource_id: null, purpose: "course_review", created_at: "2026-10-02T15:00:00Z" },
  ],
  next_before: "2026-10-02T15:00:00Z",
};

const LOG_PAGE_2 = {
  entries: [
    { id: "l-2", actor: { id: "0a7a0000-0000-4000-8000-000000000001", display_name: "Ms. Adaeze Okafor" }, subject_id: EMMA.person.id, resource: "transcript", resource_id: "s-1", purpose: "advising", created_at: "2026-09-28T10:00:00Z" },
  ],
  next_before: null,
};

async function openEmma(page: Page) {
  await page.route(`${api("/api/roster/")}**`, (route) =>
    fulfill(route, 200, { students: [{ id: EMMA.person.id, name: "Emma Smith", session_count: 0, last_active: null, total_turns: 0 }] })
  );
  await page.route(`${api("/api/student/")}**`, (route) => fulfill(route, 200, { sessions: [] }));
  await page.getByRole("button", { name: "Roster" }).click();
  await page.getByRole("button", { name: /Emma Smith/ }).click();
}

test.describe("AccessLogCanvas", () => {
  test("admin sees who read a learner's data, filters it and pages older entries", async ({ page }) => {
    await setupMockAPI(page, { me: HAYES_IN_COURSE, sessionId: SESSION_ID, turnId: TURN_ID });
    const urls: URL[] = [];
    await page.route(`${api("/api/access-log")}?**`, (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "GET") urls.push(url);
      return fulfill(route, 200, url.searchParams.get("before") ? LOG_PAGE_2 : LOG_PAGE_1);
    });
    await page.goto("/");
    await selectCourse(page, 2);
    await openEmma(page);

    const log = page.getByRole("region", { name: "Data access log" });
    await expect(log.getByRole("row", { name: /Dr. Maria Torres/ })).toContainText("Analyst summary");
    await expect(log.getByRole("row", { name: /Dr. Maria Torres/ })).toContainText("course_review");
    await expectNoSeriousAxe(page, '[data-testid="access-log-canvas"]');
    expect(urls[0].searchParams.get("subject_id")).toBe(EMMA.person.id);

    await log.getByRole("button", { name: "Load older entries" }).click();
    await expect(log.getByRole("row", { name: /Ms. Adaeze Okafor/ })).toContainText("Transcript");
    expect(urls.at(-1)?.searchParams.get("before")).toBe("2026-10-02T15:00:00Z");

    await log.getByLabel("Resource").selectOption("transcript");
    await log.getByLabel("From").fill("2026-09-01");
    await expect.poll(() => urls.at(-1)?.searchParams.get("from") ?? null).not.toBeNull();
    const last = urls.at(-1)!;
    expect(last.searchParams.get("resource")).toBe("transcript");
    expect(new Date(last.searchParams.get("from")!).getTime()).toBe(new Date("2026-09-01T00:00:00").getTime());
  });

  test("a 403 is reported, and non-admins never see the log", async ({ page }) => {
    await setupMockAPI(page, { me: HAYES_IN_COURSE, sessionId: SESSION_ID, turnId: TURN_ID });
    await page.route(`${api("/api/access-log")}?**`, (route) => fulfill(route, 403, { detail: "Forbidden" }));
    await page.goto("/");
    await selectCourse(page, 2);
    await openEmma(page);
    await expect(page.getByRole("region", { name: "Data access log" }).getByRole("alert")).toHaveText(
      "Only admins can view the access log."
    );
  });

  test("faculty learner detail has no access log", async ({ page }) => {
    await setupMockAPI(page, { me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID });
    let asked = false;
    await page.route(`${api("/api/access-log")}?**`, (route) => {
      asked = true;
      return fulfill(route, 403, { detail: "Forbidden" });
    });
    await page.goto("/");
    await selectCourse(page);
    await openEmma(page);
    await expect(page.getByText("No tutoring sessions yet.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Data access log" })).toHaveCount(0);
    expect(asked).toBe(false);
  });
});
