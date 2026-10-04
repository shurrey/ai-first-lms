import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import {
  ADMIN_ME, CS101_ID, EMMA_ID, EMMA_ME, OKAFOR_ME, PENDING_CREDENTIAL_ID, SMOKE_CSRF, TORRES_ME, corsHeaders, mockEngine, setSessionCookies,
  type FakeMe,
} from "./fake-api";
import {
  DRAFT1_ID, DRAFT2_ID, ESSAY_ID, ESSAY_TITLE, EVIDENCE_ID, FINAL_FEEDBACK, FINAL_SUBMISSION_ID, LIAM_ID, PRACTICE_ID, PRACTICE_Q1_ID,
  PRACTICE_Q2_ID, QUEUED_SUBMISSION_ID, THESIS_ID,
  submission,
} from "./fake-assessment";

test.beforeEach(async ({ context, baseURL }) => {
  await setSessionCookies(context, baseURL!);
});

async function expectNoSeriousAxe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

const ADMIN_WITH_LOG: FakeMe = {
  ...ADMIN_ME,
  capabilities: {
    ...ADMIN_ME.capabilities,
    roster: { scope: "all", access: "full" },
    improvement_view: { scope: "all", access: "aggregate" },
    learner_profile_of_others: { scope: "all", access: "full" },
  },
};

const tabs = (page: Page) => page.getByRole("navigation", { name: "Course" }).getByRole("link");

test("student revises a draft, sees feedback arrive, and reaches the practice set", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}`);
  await tabs(page).filter({ hasText: "Assignments" }).click();
  await page.getByRole("link", { name: /Transit policy essay.*Version 1 \(draft\)/ }).click();
  await expect(page.getByRole("heading", { name: ESSAY_TITLE })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/course/${CS101_ID}/assignments/${ESSAY_ID}$`));

  const feedback = page.getByRole("region", { name: "Feedback on version 1" });
  await expect(feedback.getByText("Level 2 · Developing")).toBeVisible();
  await expect(feedback.getByText("“many people say buses are good”")).toBeVisible();
  await expect(feedback.getByText("Cite one study with a number for each claim.")).toBeVisible();
  await expect(feedback.getByTestId("ai-generated-label").first()).toBeVisible();
  await expectNoSeriousAxe(page);

  // Records whether the version 2 panel ever renders version 1's feedback, even for a single commit.
  await page.evaluate(() => {
    const w = window as unknown as { staleFeedbackSeen: boolean };
    w.staleFeedbackSeen = false;
    new MutationObserver(() => {
      const heading = document.getElementById("feedback-heading");
      if (heading?.textContent?.includes("version 2") && heading.parentElement?.textContent?.includes("Level 2 · Developing")) w.staleFeedbackSeen = true;
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await page.getByLabel("Your work").fill("Revised essay with a cited figure: ridership rose 12%.");
  const posted = page.waitForRequest((r) => r.url().endsWith("/api/submissions") && r.method() === "POST");
  await page.getByRole("button", { name: "Submit draft" }).click();
  const req = await posted;
  expect(req.postDataJSON()).toEqual({
    assignment_id: ESSAY_ID, status: "draft", body_md: "Revised essay with a cited figure: ridership rose 12%.", attachments: [], parent_id: DRAFT1_ID,
  });
  expect(req.headers()["x-csrf-token"]).toBe(SMOKE_CSRF);

  const v2 = page.getByRole("region", { name: "Feedback on version 2" });
  await expect(v2.getByText(/Feedback is being generated/)).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Feedback for version 2 is ready." })).toBeAttached({ timeout: 10_000 });
  await expect(v2.getByText("Level 3 · Proficient").first()).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { staleFeedbackSeen: boolean }).staleFeedbackSeen)).toBe(false);

  const history = page.getByRole("list", { name: "Criterion changes in version 2" });
  await expect(history.getByRole("listitem").filter({ hasText: "Evidence: 3" })).toContainText("Up 1");
  await expect(history.getByRole("listitem").filter({ hasText: "Thesis: 3" })).toContainText("No change");

  await v2.getByRole("link", { name: "Practice for this" }).click();
  await expect(page).toHaveURL(new RegExp(`/practice/${PRACTICE_ID}$`));
  await expect(page.getByRole("heading", { name: "Practice: Evidence" })).toBeVisible();
  await expect(page.getByText("Which sentence gives specific evidence?")).toBeVisible();
  await expect(page.getByText(/Practice is private/)).toBeVisible();
  await expect(page.getByTestId("ai-generated-label")).toBeVisible();
  await expectNoSeriousAxe(page);

  const decision = page.waitForRequest((r) => r.url().endsWith(`/api/ai-actions/${PRACTICE_ID}/decisions`));
  await page.getByRole("button", { name: "Start practice" }).click();
  expect((await decision).postDataJSON()).toEqual({ decision: "accepted" });
  await expect(page.getByRole("status").filter({ hasText: "Marked as started." })).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("a failed feedback run says so and can be retried", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  engine.assessment.failDraft2 = true;
  await page.goto(`/course/${CS101_ID}/assignments/${ESSAY_ID}`);
  await page.getByLabel("Your work").fill("Revised essay with a cited figure.");
  await page.getByRole("button", { name: "Submit draft" }).click();

  const v2 = page.getByRole("region", { name: "Feedback on version 2" });
  await expect(v2.getByText(/Error:.*Feedback could not be generated for this version/)).toBeVisible();
  await expectNoSeriousAxe(page);
  const retry = page.waitForRequest((r) => r.url().endsWith(`/api/feedback/${DRAFT2_ID}/retry`) && r.method() === "POST");
  await v2.getByRole("button", { name: "Retry feedback" }).click();
  expect((await retry).headers()["x-csrf-token"]).toBe(SMOKE_CSRF);
  await expect(page.getByRole("status").filter({ hasText: "Feedback for version 2 is ready." })).toBeAttached({ timeout: 10_000 });
  await expect(v2.getByText("Level 3 · Proficient").first()).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("submitting a final asks for confirmation and closes the form", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  engine.assessment.pendingPolls = 0;
  await page.goto(`/course/${CS101_ID}/assignments/${ESSAY_ID}`);
  await page.getByRole("button", { name: "Submit final" }).click();
  const posted = page.waitForRequest((r) => r.url().endsWith("/api/submissions") && r.method() === "POST");
  await page.getByRole("button", { name: "Yes, submit final" }).click();
  expect((await posted).postDataJSON()).toMatchObject({ status: "final", parent_id: DRAFT1_ID });
  await expect(page.getByText(/You submitted your final version/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit draft" })).toHaveCount(0);
  expect(engine.unhandled).toEqual([]);
});

test("faculty release queued feedback with per-criterion edits and a suppression", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}`);
  await tabs(page).filter({ hasText: "Review Queue" }).click();
  await expect(page.getByRole("heading", { name: "Review Queue" })).toBeVisible();

  const card = page.getByRole("article", { name: "Feedback for Liam Chen" });
  await expect(card.getByText("Generated level: 1 · Beginning")).toBeVisible();
  await expect(card.getByTestId("ai-generated-label").first()).toBeVisible();
  await expect(page.getByRole("article", { name: "Grade for Noah Patel" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve Python Fundamentals for Emma Smith/ })).toBeVisible();
  await expectNoSeriousAxe(page);

  await card.getByRole("button", { name: "Edit Evidence" }).click();
  await card.getByLabel("Level for Evidence").fill("2");
  await card.getByLabel("Next step for Evidence").fill("Add one statistic per paragraph.");
  await card.getByLabel("Suppress Thesis").check();
  const release = page.waitForRequest((r) => r.url().endsWith(`/api/feedback/${QUEUED_SUBMISSION_ID}/release`));
  await card.getByRole("button", { name: "Release to Liam Chen" }).click();
  const body = (await release).postDataJSON();
  expect(body).toEqual({
    action: "release",
    edits: [
      { criterion_id: THESIS_ID, suppress: true },
      { criterion_id: EVIDENCE_ID, score: 2, next_step: "Add one statistic per paragraph." },
    ],
    reason: null,
  });
  await expect(page.getByRole("status").filter({ hasText: "Feedback for Liam Chen released." })).toBeAttached();
  await expect(page.getByText("No feedback is waiting for release.")).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

function commitPreview(gradeId: string, submissionId: string) {
  return {
    tool: "assessments.commit_grade",
    arguments: { grade_id: gradeId },
    artifact: {
      grade: { grade_id: gradeId, submission_id: submissionId, scores: { thesis: 3, evidence: 2 },
        holistic_md: '<user_content source="grade">Strong revision.</user_content>' },
      requires: { final_scores: ["thesis", "evidence"], holistic_md: true },
    },
  };
}

test("grade commit needs every final score and a closing comment, then waits for approval", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  let approved = false;
  let refuseNext = true;
  await page.route((url) => url.pathname === "/api/stream", (route) => {
    const events = [
      { event: "agent_start", payload: { step_id: "s1", agent: "grading_assistant", inputs: {} } },
      { event: "approval_request", payload: { approval_id: "ap-1", step_id: "s1", agent: "grading_assistant", action: "Commit grade for Noah Patel",
        preview: commitPreview("g-1", FINAL_SUBMISSION_ID), artifact_type: "grade_commit" } },
      ...(approved ? [{ event: "final", payload: { answer_markdown: "Grade committed.", artifacts: [], ai_action_ids: [], cost_usd: 0, tokens: 0, wall_time_ms: 1 } }] : []),
    ];
    return route.fulfill({ status: 200, contentType: "text/event-stream", headers: corsHeaders(route.request()),
      body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") });
  });
  await page.route((url) => url.pathname === "/api/approval", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    if (refuseNext) {
      refuseNext = false;
      return route.fulfill({ status: 422, contentType: "application/json", headers: corsHeaders(route.request()),
        body: JSON.stringify({ detail: "Committing a grade needs your final score on every criterion; missing: evidence." }) });
    }
    approved = true;
    const { approval_id, decision } = route.request().postDataJSON();
    return route.fulfill({ status: 202, contentType: "application/json", headers: corsHeaders(route.request()),
      body: JSON.stringify({ status: "accepted", approval_id, decision }) });
  });

  await page.goto(`/course/${CS101_ID}/review`);
  const card = page.getByRole("article", { name: "Grade for Noah Patel" });
  await expect(card.getByText(/Transit policy essay · final version 3/)).toBeVisible();
  await card.getByRole("button", { name: "Commit grade" }).click();
  const alert = card.getByRole("alert");
  await expect(alert).toContainText("Enter a final score for Thesis.");
  await expect(alert).toContainText("Enter a final score for Evidence.");
  await expect(alert).toContainText("Write a closing comment.");
  expect(engine.requests.some((r) => r.path === "/api/converse")).toBe(false);

  await card.getByLabel(/Thesis/).fill("3");
  await card.getByLabel(/Evidence/).fill("3");
  await card.getByLabel("Closing comment (required)").fill("Strong revision.");
  const converse = page.waitForRequest((r) => r.url().endsWith("/api/converse"));
  await card.getByRole("button", { name: "Commit grade" }).click();
  const message = (await converse).postDataJSON().message as string;
  expect(message).toContain(FINAL_SUBMISSION_ID);
  expect(message).toContain("- evidence: 3");
  expect(message).toContain('Instructor closing comment: "Strong revision."');

  const approval = page.getByRole("region", { name: /Approval needed: Commit grade for Noah Patel/ });
  await expect(approval).toBeVisible();
  await expect(approval.getByRole("heading")).toBeFocused();
  await expect(approval.getByRole("spinbutton", { name: /thesis/ })).toHaveValue("3");
  await expect(approval.getByRole("spinbutton", { name: /evidence/ })).toHaveValue("3");
  await expect(approval.getByLabel("Closing comment (required)")).toHaveValue("Strong revision.");
  await expect(approval.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expectNoSeriousAxe(page);

  await approval.getByRole("spinbutton", { name: /evidence/ }).fill("");
  await approval.getByRole("button", { name: "Commit with my scores" }).click();
  await expect(approval.getByRole("alert")).toContainText("Enter a whole-number final score for evidence.");
  await approval.getByRole("spinbutton", { name: /evidence/ }).fill("3");

  const expected = { session_id: "smoke-session-faculty", turn_id: "smoke-turn-1", approval_id: "ap-1", decision: "edit",
    edited_payload: { grade_id: "g-1", final_scores: { thesis: 3, evidence: 3 }, holistic_md: "Strong revision." } };
  const refused = page.waitForRequest((r) => r.url().endsWith("/api/approval"));
  await approval.getByRole("button", { name: "Commit with my scores" }).click();
  expect((await refused).postDataJSON()).toEqual(expected);
  await expect(approval.getByRole("alert")).toContainText("missing: evidence");

  const accepted = page.waitForRequest((r) => r.url().endsWith("/api/approval"));
  await approval.getByRole("button", { name: "Commit with my scores" }).click();
  expect((await accepted).postDataJSON()).toEqual(expected);
  await expect(page.getByText("Grade committed.")).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("grades committed back to back with the panel open each start a turn, and committed grades leave the list", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  const liamFinalId = "d6000000-0000-4000-8000-0000000000d6";
  engine.assessment.finals.push({
    submission: submission(liamFinalId, 2, "final", LIAM_ID, { feedback_status: "none" }),
    feedback: { ...FINAL_FEEDBACK, submission_id: liamFinalId, person_id: LIAM_ID, student_name: "Liam Chen" },
  });
  const turns: string[] = [];
  const approvedTurns = new Set<string>();
  const finalFor: Record<string, string> = {};
  const studentFor: Record<string, string> = {};

  await page.route((url) => url.pathname === "/api/converse", (route) => {
    const { session_id, message } = route.request().postDataJSON() as { session_id: string; message: string };
    const turnId = `commit-turn-${turns.length + 1}`;
    turns.push(message);
    finalFor[turnId] = message.includes(liamFinalId) ? liamFinalId : FINAL_SUBMISSION_ID;
    studentFor[turnId] = message.includes(liamFinalId) ? "Liam Chen" : "Noah Patel";
    return route.fulfill({ status: 202, contentType: "application/json", headers: corsHeaders(route.request()),
      body: JSON.stringify({ turn_id: turnId, stream_url: `/api/stream?session_id=${session_id}&turn_id=${turnId}` }) });
  });
  await page.route((url) => url.pathname === "/api/stream", (route) => {
    const turnId = new URL(route.request().url()).searchParams.get("turn_id") ?? "";
    const events = [
      { event: "approval_request", payload: { approval_id: `ap-${turnId}`, step_id: "s1", agent: "grading_assistant", action: `Commit grade for ${studentFor[turnId]}`,
        preview: commitPreview(`g-${turnId}`, finalFor[turnId]),
        artifact_type: "grade_commit" } },
      ...(approvedTurns.has(turnId) ? [{ event: "final", payload: { answer_markdown: `Committed ${studentFor[turnId]}.`, artifacts: [], ai_action_ids: [], cost_usd: 0, tokens: 0, wall_time_ms: 1 } }] : []),
    ];
    return route.fulfill({ status: 200, contentType: "text/event-stream", headers: corsHeaders(route.request()),
      body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") });
  });
  await page.route((url) => url.pathname === "/api/approval", (route) => {
    const { turn_id, approval_id, decision } = route.request().postDataJSON();
    approvedTurns.add(turn_id);
    const final = engine.assessment.finals.find((f) => f.submission.id === finalFor[turn_id])!;
    final.feedback = { ...final.feedback, criteria: (final.feedback.criteria as Record<string, unknown>[]).map((c) => ({ ...c, final_score: 3 })) };
    return route.fulfill({ status: 202, contentType: "application/json", headers: corsHeaders(route.request()),
      body: JSON.stringify({ status: "accepted", approval_id, decision }) });
  });

  await page.goto(`/course/${CS101_ID}/review`);
  const fillAndCommit = async (who: string) => {
    const card = page.getByRole("article", { name: `Grade for ${who}` });
    await card.getByLabel(/Thesis/).fill("3");
    await card.getByLabel(/Evidence/).fill("3");
    await card.getByLabel("Closing comment (required)").fill("Strong revision.");
    await card.getByRole("button", { name: "Commit grade" }).click();
  };

  await fillAndCommit("Noah Patel");
  const first = page.getByRole("region", { name: /Approval needed: Commit grade for Noah Patel/ });
  await expect(first).toBeVisible();
  await expect(first).toContainText("holistic md:Strong revision.");
  await expect(first).toContainText("grade id:g-commit-turn-1");
  await expect(first).not.toContainText("user_content");
  await expect(first).not.toContainText("{");
  await expectNoSeriousAxe(page);

  await fillAndCommit("Liam Chen");
  expect(turns).toHaveLength(1);

  await first.getByRole("button", { name: "Commit with my scores" }).click();
  await expect(page.getByRole("textbox", { name: "Message the AI assistant" })).toBeFocused();
  await expect(page.getByText("Committed Noah Patel.")).toBeVisible();
  await expect(page.getByRole("article", { name: "Grade for Noah Patel" })).toHaveCount(0);

  const second = page.getByRole("region", { name: /Approval needed: Commit grade for Liam Chen/ });
  await expect(second).toBeVisible();
  expect(turns).toHaveLength(2);
  expect(turns[1]).toContain(liamFinalId);
  await second.getByRole("button", { name: "Commit with my scores" }).click();
  await expect(page.getByText("Committed Liam Chen.")).toBeVisible();
  await expect(page.getByText("No final submissions are waiting for a grade.")).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("faculty reject a pending credential with a reason", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}/review`);
  await page.getByRole("button", { name: /Reject Python Fundamentals for Emma Smith/ }).click();
  await page.getByLabel("Reason for rejecting (optional)").fill("Needs one more session.");
  const reject = page.waitForRequest((r) => r.url().endsWith(`/api/reject-credential/${PENDING_CREDENTIAL_ID}`));
  await page.getByRole("button", { name: "Confirm reject" }).click();
  expect((await reject).postDataJSON()).toEqual({ reviewer_id: TORRES_ME.person.id, reason: "Needs one more session." });
  await expect(page.getByText("No credentials are waiting for review.")).toBeVisible();
  expect(engine.unhandled).toEqual([]);
});

test("Improvement grid shows trajectories with text flags and drills down to feedback", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}`);
  await tabs(page).filter({ hasText: "Improvement" }).click();
  const grid = page.getByRole("table", { name: /Student by criterion trajectories/ });
  const emma = grid.getByRole("row", { name: /Emma Smith/ });
  await expect(emma).toContainText("2 → 3");
  await expect(emma).toContainText("Up 1");
  await expect(emma).toContainText("Improving");
  await expect(emma).toContainText("Ready for summative");
  const liam = grid.getByRole("row", { name: /Liam Chen/ });
  await expect(liam).toContainText("Plateaued");
  await expect(liam).toContainText("Regressed");
  await expect(liam).toContainText("Down 1");
  await expectNoSeriousAxe(page);

  await emma.getByRole("button", { name: /Emma Smith, Evidence: 2 → 3, Improving/ }).click();
  await expect(page.getByRole("heading", { name: "Emma Smith · Evidence" })).toBeFocused();
  await page.getByRole("button", { name: "Feedback for version 1" }).click();
  await expect(page.getByText("Level 2 · Developing")).toBeVisible();
  await expectNoSeriousAxe(page);
  expect(engine.unhandled).toEqual([]);
});

test("aggregate-only roles see Improvement counts without students", async ({ page }) => {
  const engine = await mockEngine(page, { me: ADMIN_WITH_LOG });
  await page.goto(`/course/${CS101_ID}/improvement`);
  const table = page.getByRole("table", { name: /Aggregate across students/ });
  await expect(table.getByRole("row", { name: /Evidence/ })).toContainText("1");
  await expect(page.getByText("Emma Smith")).toHaveCount(0);
  expect(engine.unhandled).toEqual([]);
});

test("admin reads a learner's access log with filters and paging", async ({ page }) => {
  const engine = await mockEngine(page, { me: ADMIN_WITH_LOG });
  await page.goto(`/learners/${EMMA_ID}/access-log?name=Emma%20Smith`);
  await expect(page.getByRole("heading", { name: "Data access log: Emma Smith" })).toBeVisible();
  const table = page.getByRole("table", { name: /Data access entries/ });
  await expect(table.getByRole("row", { name: /Analyst summary/ })).toContainText("Dr. Maria Torres");
  await expect(table.getByRole("row", { name: /Submission/ })).toContainText("Not recorded");
  await expectNoSeriousAxe(page);

  const more = page.waitForRequest((r) => r.url().includes("/api/access-log?") && r.url().includes("before="));
  await page.getByRole("button", { name: "Load older entries" }).click();
  expect(new URL((await more).url()).searchParams.get("before")).toBe("2026-09-29T15:00:00Z");
  await expect(table.getByRole("row", { name: /Tutor transcript/ })).toContainText("Ms. Adaeze Okafor");
  await expect(page.getByRole("button", { name: "Load older entries" })).toHaveCount(0);

  await page.getByLabel("Resource").selectOption("submission");
  await page.getByLabel("From").fill("2026-09-01");
  await page.getByLabel("To (inclusive)").fill("2026-09-30");
  const filtered = page.waitForRequest((r) => r.url().includes("/api/access-log?") && r.url().includes("resource="));
  await page.getByRole("button", { name: "Apply" }).click();
  const params = new URL((await filtered).url()).searchParams;
  expect(params.get("subject_id")).toBe(EMMA_ID);
  expect(params.get("resource")).toBe("submission");
  expect(params.get("from")).toBe("2026-09-01T00:00:00.000Z");
  expect(params.get("to")).toBe("2026-10-01T00:00:00.000Z");
  expect(engine.unhandled).toEqual([]);
});

test("new routes show the no-access state without the capability or on a 403", async ({ page }) => {
  await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/learners/${EMMA_ID}/access-log`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();
  await page.goto(`/course/${CS101_ID}/assignments`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();

  const engine = await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}/review`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();
  await expect(tabs(page).filter({ hasText: "Review Queue" })).toHaveCount(0);
  await expect(tabs(page).filter({ hasText: "Improvement" })).toHaveCount(0);

  engine.statusOverrides[`GET /api/submissions`] = 403;
  await page.goto(`/course/${CS101_ID}/assignments`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();
});

test("practice answers are checked one item at a time from the keyboard, with results announced", async ({ page }) => {
  const engine = await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}/practice/${PRACTICE_ID}`);
  await expect(page.getByText(/Practice is private\. Only you see your answers and results; your instructor sees only counts of practice sets generated, started and marked not helpful\./)).toBeVisible();
  await expect(page.getByText(/practice attempts were made/)).toHaveCount(0);

  const q1 = page.getByRole("form", { name: /Which sentence gives specific evidence/ });
  await q1.getByRole("radio", { name: "A. Buses are good." }).focus();
  await page.keyboard.press("Space");
  const wrong = page.waitForRequest((r) => r.url().endsWith(`/api/practice/${PRACTICE_ID}/attempts`));
  await page.keyboard.press("Tab");
  await expect(q1.getByRole("button", { name: "Check answer to question 1" })).toBeFocused();
  await page.keyboard.press("Enter");
  const wrongReq = await wrong;
  expect(wrongReq.postDataJSON()).toEqual({ answers: [{ question_id: PRACTICE_Q1_ID, answer: "A" }] });
  expect(wrongReq.headers()["x-csrf-token"]).toBe(SMOKE_CSRF);
  const q1Status = q1.getByRole("status");
  await expect(q1Status).toHaveAttribute("aria-live", "polite");
  await expect(q1Status).toContainText("Not quite. Expected: B. Ridership rose 12% in 2024. A figure with a year is specific evidence.");

  await q1.getByRole("radio", { name: "B. Ridership rose 12% in 2024." }).focus();
  await page.keyboard.press("Space");
  await q1.getByRole("button", { name: "Check answer to question 1" }).press("Enter");
  await expect(q1Status).toContainText("Correct.");
  await expect(q1Status).not.toContainText("Not quite");
  await expect(q1.getByRole("button", { name: "Check answer to question 1" })).toBeDisabled();

  const q2 = page.getByRole("form", { name: /Rewrite this claim/ });
  await q2.getByRole("button", { name: "Check answer to question 2" }).click();
  await expect(q2.getByRole("status")).toContainText("Choose or write an answer first.");
  await q2.getByLabel("Your answer to question 2").fill("Ridership rose 12% (City Transit, 2024).");
  await q2.getByRole("button", { name: "Check answer to question 2" }).click();
  await expect(q2.getByRole("status")).toContainText(
    "Answer recorded. This item isn't scored automatically. Model answer: Names the source; States the figure.");
  expect(engine.assessment.practiceAttempts.at(-1)).toEqual({ answers: [{ question_id: PRACTICE_Q2_ID, answer: "Ridership rose 12% (City Transit, 2024)." }] });
  await expect(q2.getByRole("button", { name: "Check answer to question 2" })).toBeDisabled();
  expect(engine.assessment.practiceAttempts).toHaveLength(3);
  await expectNoSeriousAxe(page);
  expect(engine.unhandled).toEqual([]);
});

const ADVISOR_IN_COURSE: FakeMe = {
  ...OKAFOR_ME,
  capabilities: { ...OKAFOR_ME.capabilities, improvement_view: { scope: "assigned", access: "summary" } },
};

test("advisors see Improvement scores but no criterion feedback", async ({ page }) => {
  const engine = await mockEngine(page, { me: ADVISOR_IN_COURSE });
  await page.goto(`/course/${CS101_ID}/improvement`);
  const grid = page.getByRole("table", { name: /Student by criterion trajectories/ });
  await grid.getByRole("button", { name: /Emma Smith, Evidence: 2 → 3/ }).click();
  await expect(page.getByRole("heading", { name: "Emma Smith · Evidence" })).toBeFocused();
  await expect(page.getByRole("button", { name: /Feedback for version/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toHaveCount(0);
  expect(engine.requests.some((r) => r.path.startsWith("/api/feedback/"))).toBe(false);
  await expectNoSeriousAxe(page);
});

const ALIGNMENT_LEVELS = [
  { score: 1, label: "Beginning", descriptor: "No clear claim." },
  { score: 2, label: "Developing", descriptor: "Claim is vague." },
  { score: 3, label: "Proficient", descriptor: "Claim is specific and arguable." },
];

test("faculty accept, edit and reject an alignment proposal from the assignment's alignment view", async ({ page }) => {
  const engine = await mockEngine(page, { me: TORRES_ME });
  await page.route((url) => url.pathname === "/api/stream" && url.searchParams.get("turn_id") === "smoke-turn-1", (route) => {
    const events = [
      { event: "agent_start", payload: { step_id: "s1", agent: "course_architect", inputs: {} } },
      { event: "final", payload: {
        answer_markdown: "Proposed two outcomes and three criteria.",
        ai_action_ids: ["aa000000-0000-4000-8000-0000000000a1"],
        artifacts: [{ artifact_id: "d1", type: "content_draft", data: {
          title: "Alignment proposal: Transit policy essay", kind: "alignment_proposal", assignment_node: ESSAY_ID,
          outcomes: [
            { node_id: "o-1", title: "Construct an arguable thesis", reason: "Week 2 of the syllabus." },
            { node_id: "o-2", title: "Integrate cited evidence", reason: "The prompt asks for two sources." },
          ],
          criteria: [
            { key: "thesis", description: "States a clear, arguable thesis.", levels: ALIGNMENT_LEVELS, outcome_nodes: ["o-1"] },
            { key: "evidence", description: "Uses evidence.", levels: ALIGNMENT_LEVELS, outcome_nodes: ["o-2"] },
            { key: "style", description: "Uses varied sentences.", levels: ALIGNMENT_LEVELS, outcome_nodes: [] },
          ],
        } }],
        cost_usd: 0, tokens: 0, wall_time_ms: 1,
      } },
    ];
    return route.fulfill({ status: 200, contentType: "text/event-stream", headers: corsHeaders(route.request()),
      body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") });
  });

  await page.goto(`/course/${CS101_ID}/review`);
  await page.getByRole("article", { name: "Grade for Noah Patel" }).getByRole("link", { name: `Outcome alignment for ${ESSAY_TITLE}` }).click();
  await expect(page).toHaveURL(new RegExp(`/course/${CS101_ID}/alignment/${ESSAY_ID}$`));
  const converse = page.waitForRequest((r) => r.url().endsWith("/api/converse"));
  await page.getByRole("button", { name: "Propose alignment" }).click();
  expect((await converse).postDataJSON().message).toContain(ESSAY_ID);

  const review = page.getByRole("region", { name: "Alignment proposal: Transit policy essay" });
  await expect(review.getByText("Why: Week 2 of the syllabus.")).toBeVisible();
  await expect(review.getByRole("checkbox", { name: /^Accept/ })).toHaveCount(0);
  await review.getByRole("group", { name: "Decision for Evidence" }).getByRole("radio", { name: "Edit" }).check();
  await review.getByLabel("Evidence description").fill("Supports each claim with cited evidence.");
  await review.getByLabel("Evidence level 2 (Developing)").fill("Some claims cite evidence.");
  await review.getByRole("group", { name: "Evidence aligned outcomes" }).getByRole("checkbox", { name: "Construct an arguable thesis" }).check();
  await review.getByRole("group", { name: "Decision for Style" }).getByRole("radio", { name: "Reject" }).check();
  await review.getByLabel("Why reject Style? (optional)").fill("Not assessed in this essay.");
  await expectNoSeriousAxe(page);

  const saved = page.waitForRequest((r) => r.url().endsWith(`/api/assignments/${ESSAY_ID}/alignment/decisions`));
  await review.getByRole("button", { name: "Save decisions" }).click();
  const req = await saved;
  expect(req.headers()["x-csrf-token"]).toBe(SMOKE_CSRF);
  expect(req.postDataJSON()).toEqual({
    decisions: [
      { key: "thesis", decision: "accept" },
      { key: "evidence", decision: "edit", criterion: { key: "evidence", description: "Supports each claim with cited evidence.",
        levels: ALIGNMENT_LEVELS.map((l) => (l.score === 2 ? { ...l, descriptor: "Some claims cite evidence." } : l)), outcome_nodes: ["o-2", "o-1"] } },
      { key: "style", decision: "reject", reason: "Not assessed in this essay." },
    ],
  });
  await expect(review.getByRole("status").filter({ hasText: "Decisions saved." })).toBeVisible();
  await expect(review.getByRole("button", { name: "Save decisions" })).toHaveCount(0);
  expect(engine.unhandled).toEqual([]);
});

test("faculty reach the alignment view from a draft awaiting release, before any final is graded", async ({ page }) => {
  await mockEngine(page, { me: TORRES_ME });
  await page.goto(`/course/${CS101_ID}/review`);
  await page.getByRole("article", { name: "Feedback for Liam Chen" }).getByRole("link", { name: "Outcome alignment for Liam Chen's assignment" }).click();
  await expect(page).toHaveURL(new RegExp(`/course/${CS101_ID}/alignment/${ESSAY_ID}$`));
  await expect(page.getByRole("button", { name: "Propose alignment" })).toBeVisible();
});

test("the alignment view is for the course's faculty only", async ({ page }) => {
  await mockEngine(page, { me: EMMA_ME });
  await page.goto(`/course/${CS101_ID}/alignment/${ESSAY_ID}`);
  await expect(page.getByRole("heading", { name: "You don't have access to this" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Propose alignment" })).toHaveCount(0);
});
