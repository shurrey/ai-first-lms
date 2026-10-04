import { expect, test, type Page, type Request } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { CS101_ID, EMMA, HAYES, OKAFOR, TORRES, api, fulfill, type FakeMe } from "./fixtures/fake-api";
import { selectCourse, setupMockAPI } from "./fixtures/setup";

const SESSION_ID = "fl-session";
const TURN_ID = "fl-turn";
const SUBMISSION_ID = "5a000000-0000-4000-8000-000000000001";
const REVISION_ID = "5a000000-0000-4000-8000-000000000002";
const PRACTICE_ID = "9a000000-0000-4000-8000-000000000001";
const THESIS = "c0000000-0000-4000-8000-000000000001";
const EVIDENCE = "c0000000-0000-4000-8000-000000000002";

const own = (access = "full") => ({ scope: "own", access });
const self = (access = "full") => ({ scope: "self", access });

const WATSON: FakeMe = {
  ...TORRES,
  capabilities: {
    ...TORRES.capabilities,
    feedback_release: own(),
    grade_commit: own(),
    improvement_view: own(),
    ai_actions_log: own("read"),
  },
};

const EMMA_LOOP: FakeMe = {
  ...EMMA,
  capabilities: {
    ...EMMA.capabilities,
    submit_work: self(),
    improvement_view: self("read"),
    ai_actions_log: self("read"),
  },
};

const HAYES_IN_COURSE: FakeMe = {
  ...HAYES,
  enrollments: [{ course_id: CS101_ID, slug: "cs101", title: "CS 101 — Intro to Computer Science", role: "observer" }],
  capabilities: { ...HAYES.capabilities, improvement_view: { scope: "all", access: "aggregate" } },
};

function criteria(released: string | null) {
  return [
    {
      criterion_id: THESIS,
      criterion_key: "thesis",
      description: "States a clear, arguable thesis.",
      ai_score: 3,
      level_label: "Proficient",
      ai_rationale: "The thesis is specific and arguable.",
      evidence_spans: [{ quote: "Cities should fund bike lanes before parking.", start: 0, end: 45 }],
      next_step: "Preview your two main reasons in the thesis sentence.",
      ai_action_id: null,
      released_at: released,
    },
    {
      criterion_id: EVIDENCE,
      criterion_key: "evidence",
      description: "Supports claims with cited evidence.",
      ai_score: 2,
      level_label: "Developing",
      ai_rationale: "Claims rely on anecdote.",
      evidence_spans: [{ quote: "Everyone I know bikes to work." }],
      next_step: "Add one statistic from a cited source.",
      ai_action_id: null,
      released_at: released,
    },
  ];
}

function feedback(status: string, extra: Record<string, unknown> = {}) {
  return {
    submission_id: SUBMISSION_ID,
    assignment_id: "a0000000-0000-4000-8000-000000000001",
    person_id: EMMA.person.id,
    student_name: "Emma Smith",
    status,
    release_mode: "instructor_release",
    criteria: status === "released" ? criteria("2026-10-01T12:00:00Z") : status === "pending" ? [] : criteria(null),
    practice_set_ai_action_id: null,
    ...extra,
  };
}

const PRACTICE_ACTION = {
  id: PRACTICE_ID,
  agent: "content_generator",
  action_type: "practice_item",
  subject_person_id: EMMA.person.id,
  course_id: CS101_ID,
  sources: [],
  policies: [],
  output: {
    tool: "content.generate_practice",
    criterion_id: EVIDENCE,
    student_id: EMMA.person.id,
    count: 3,
    practice_set_id: "ps-1",
    question_ids: ["q1", "q2", "q3"],
    items: [
      { type: "mcq", stem: "Which source is strongest evidence?", options: { A: "A blog comment", B: "A city transport survey" }, answer_key: { correct: "B", explanation: "A survey samples many riders." }, bloom_level: "evaluate" },
      { type: "short_answer", stem: "Rewrite this claim with a cited statistic.", answer_key: { model_points: ["Names the source", "States the figure"] }, bloom_level: "apply" },
      { type: "short_answer", stem: "Name one place to find transport data.", answer_key: "A city open-data portal", bloom_level: "remember" },
    ],
  },
  created_at: "2026-10-01T12:05:00Z",
  decisions: [],
};

const IMPROVEMENT = {
  course_id: CS101_ID,
  criteria: [
    { criterion_id: THESIS, criterion_key: "thesis", description: "Thesis", target_score: 3 },
    { criterion_id: EVIDENCE, criterion_key: "evidence", description: "Evidence", target_score: 3 },
  ],
  students: [
    {
      student_id: EMMA.person.id,
      display_name: "Emma Smith",
      trajectories: [
        {
          criterion_id: THESIS,
          points: [
            { submission_id: SUBMISSION_ID, version: 1, status: "draft", score: 3, submitted_at: "2026-09-20T12:00:00Z" },
            { submission_id: REVISION_ID, version: 2, status: "draft", score: 3, submitted_at: "2026-09-27T12:00:00Z" },
          ],
          latest_delta: 0,
          flag: "plateaued",
        },
        {
          criterion_id: EVIDENCE,
          points: [
            { submission_id: SUBMISSION_ID, version: 1, status: "draft", score: 2, submitted_at: "2026-09-20T12:00:00Z" },
            { submission_id: REVISION_ID, version: 2, status: "draft", score: 3, submitted_at: "2026-09-27T12:00:00Z" },
          ],
          latest_delta: 1,
          flag: "improving",
        },
      ],
    },
  ],
};

async function expectNoSeriousAxe(page: Page, selector = "dialog") {
  const results = await new AxeBuilder({ page }).include(selector).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

async function signIn(page: Page, me: FakeMe) {
  await setupMockAPI(page, { me, sessionId: SESSION_ID, turnId: TURN_ID });
  await page.goto("/");
}

test.describe("FeedbackCanvas: faculty review queue", () => {
  test("Dr. Watson edits one criterion, holds another back and releases", async ({ page }) => {
    await signIn(page, WATSON);
    await page.route(`${api("/api/feedback/queue")}**`, (route) => fulfill(route, 200, { items: [feedback("awaiting_release")] }));
    await page.route(api(`/api/feedback/${SUBMISSION_ID}`), (route) => fulfill(route, 200, feedback("awaiting_release")));
    const released: Request[] = [];
    await page.route(api(`/api/feedback/${SUBMISSION_ID}/release`), (route) => {
      if (route.request().method() === "POST") released.push(route.request());
      return fulfill(route, 200, feedback("released"));
    });
    await selectCourse(page);

    const queue = page.getByRole("region", { name: "Review queue" });
    await expect(queue.getByText("Feedback awaiting release (1)")).toBeVisible();
    await queue.getByRole("button", { name: /Emma Smith/ }).click();

    const dialog = page.getByRole("dialog", { name: "Feedback" });
    await expect(dialog.getByText("Awaiting instructor release · instructor release")).toBeVisible();
    await expect(dialog.getByText("“Everyone I know bikes to work.”")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "AI-generated · sources" }).first()).toBeVisible();
    await expectNoSeriousAxe(page);

    await dialog.getByRole("button", { name: "Edit Evidence" }).click();
    await dialog.getByLabel("Evidence next step").fill("Add one statistic from the city transport survey.");
    await dialog.getByLabel("Don't release Thesis").check();
    await expectNoSeriousAxe(page);
    await dialog.getByRole("button", { name: "Release to student" }).click();

    await expect(dialog.getByText("Released · instructor release")).toBeVisible();
    expect(released).toHaveLength(1);
    expect(released[0].headers()["x-csrf-token"]).toBe("smoke-csrf-token");
    expect(released[0].postDataJSON()).toEqual({
      action: "release",
      edits: [
        { criterion_id: THESIS, suppress: true },
        { criterion_id: EVIDENCE, next_step: "Add one statistic from the city transport survey." },
      ],
      reason: null,
    });
  });

  test("Suppress all sends a suppress decision without edits", async ({ page }) => {
    await signIn(page, WATSON);
    await page.route(`${api("/api/feedback/queue")}**`, (route) => fulfill(route, 200, { items: [feedback("awaiting_release")] }));
    await page.route(api(`/api/feedback/${SUBMISSION_ID}`), (route) => fulfill(route, 200, feedback("awaiting_release")));
    let body: unknown = null;
    await page.route(api(`/api/feedback/${SUBMISSION_ID}/release`), (route) => {
      if (route.request().method() === "POST") body = route.request().postDataJSON();
      return fulfill(route, 200, feedback("suppressed"));
    });
    await selectCourse(page);
    await page.getByRole("region", { name: "Review queue" }).getByRole("button", { name: /Emma Smith/ }).click();
    const dialog = page.getByRole("dialog", { name: "Feedback" });
    await dialog.getByLabel("Note for the record (optional)").fill("Off-topic draft");
    await dialog.getByRole("button", { name: "Suppress all" }).click();
    await expect(dialog.getByText("Suppressed · instructor release")).toBeVisible();
    expect(body).toEqual({ action: "suppress", reason: "Off-topic draft" });
  });

  test("a 409 on release explains why", async ({ page }) => {
    await signIn(page, WATSON);
    await page.route(`${api("/api/feedback/queue")}**`, (route) => fulfill(route, 200, { items: [feedback("awaiting_release")] }));
    await page.route(api(`/api/feedback/${SUBMISSION_ID}`), (route) => fulfill(route, 200, feedback("awaiting_release")));
    await page.route(api(`/api/feedback/${SUBMISSION_ID}/release`), (route) => fulfill(route, 409, { detail: "already released" }));
    await selectCourse(page);
    await page.getByRole("region", { name: "Review queue" }).getByRole("button", { name: /Emma Smith/ }).click();
    const dialog = page.getByRole("dialog", { name: "Feedback" });
    await dialog.getByRole("button", { name: "Release to student" }).click();
    await expect(dialog.getByRole("alert")).toHaveText(/already released or suppressed/);
  });

  test("no review queue without the feedback_release capability", async ({ page }) => {
    await signIn(page, TORRES);
    await selectCourse(page);
    await expect(page.getByRole("region", { name: "Review queue" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open Improvement" })).toHaveCount(0);
  });
});

test.describe("FeedbackCanvas and PracticeSetCanvas: student", () => {
  test("Emma sees nothing until feedback is released, then criteria, spans and practice", async ({ page }) => {
    await signIn(page, EMMA_LOOP);
    await page.route(`${api("/api/submissions")}?**`, (route) =>
      fulfill(route, 200, {
        items: [{ id: SUBMISSION_ID, person_id: EMMA.person.id, assignment_id: "a0000000-0000-4000-8000-000000000001", assignment_title: "Bike lanes essay", version: 1, status: "draft", submitted_at: "2026-10-01T11:00:00Z", feedback_status: "pending" }],
      })
    );
    let polls = 0;
    await page.route(api(`/api/feedback/${SUBMISSION_ID}`), (route) => {
      polls += 1;
      return fulfill(route, 200, polls === 1 ? feedback("pending") : feedback("released", { practice_set_ai_action_id: PRACTICE_ID }));
    });
    await page.route(`${api("/api/submissions/")}*/history`, (route) => fulfill(route, 404, { detail: "Not found" }));
    await page.route(api(`/api/ai-actions/${PRACTICE_ID}`), (route) => fulfill(route, 200, PRACTICE_ACTION));
    await page.route(`${api("/api/ai-actions")}?**`, (route) => fulfill(route, 200, { items: [PRACTICE_ACTION] }));
    const attempts: unknown[] = [];
    await page.route(api(`/api/practice/${PRACTICE_ID}/attempts`), (route) => {
      const body = route.request().postDataJSON() as { answers: Array<{ question_id: string; answer: string }> };
      attempts.push(body);
      const keys: Record<string, { expected: string; feedback: string | null }> = {
        q1: { expected: "B", feedback: "A survey samples many riders." },
        q2: { expected: "Names the source; States the figure", feedback: null },
      };
      const results = body.answers.map(({ question_id, answer }) => ({
        question_id,
        correct: question_id === "q1" ? answer === "B" : null,
        expected: keys[question_id]?.expected ?? null,
        feedback: keys[question_id]?.feedback ?? null,
      }));
      return fulfill(route, 201, {
        practice_set_id: PRACTICE_ID,
        attempt_id: `att-${attempts.length}`,
        correct: results.filter((r) => r.correct === true).length,
        total: results.length,
        results,
      });
    });
    let decision: unknown = null;
    await page.route(api(`/api/ai-actions/${PRACTICE_ID}/decisions`), (route) => {
      if (route.request().method() === "POST") decision = route.request().postDataJSON();
      return fulfill(route, 201, { id: "hd-1", ai_action_id: PRACTICE_ID, decided_by: EMMA.person.id, decision: "accepted", decided_at: "2026-10-01T12:10:00Z" });
    });
    await selectCourse(page);

    await page.getByRole("region", { name: "My feedback" }).getByRole("button", { name: /Bike lanes essay, version 1 \(draft\)/ }).click();
    const dialog = page.getByRole("dialog", { name: "Feedback" });
    await expect(dialog.getByText(/Feedback is being generated/)).toBeVisible();
    await expect(dialog.getByText("Everyone I know bikes to work.")).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Release to student" })).toHaveCount(0);

    await expect(dialog.getByText("“Everyone I know bikes to work.”")).toBeVisible({ timeout: 15000 });
    await expect(dialog.getByText("Feedback status: Released.")).toBeAttached();
    await expect(dialog.getByText("Level 2 · Developing")).toBeVisible();
    await expect(dialog.getByText("Add one statistic from a cited source.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Edit Evidence" })).toHaveCount(0);
    await expectNoSeriousAxe(page);

    await dialog.getByRole("button", { name: "Practice for this" }).click();
    const practice = page.getByRole("dialog", { name: "Practice" });
    await expect(practice.getByText("Private to you. Your answers and results are visible only to you.")).toBeVisible();
    await expect(practice.getByText(/practice attempts you made/)).toHaveCount(0);
    await expect(practice.getByText("Which source is strongest evidence?")).toBeVisible();

    await practice.getByRole("radio", { name: "A. A blog comment" }).focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("Tab");
    await expect(practice.getByRole("button", { name: "Check answer for question 1" })).toBeFocused();
    await page.keyboard.press("Enter");
    const q1 = practice.getByRole("form", { name: "Which source is strongest evidence?" });
    await expect(q1.getByRole("status")).toHaveText("Not quite. Expected: B. A city transport survey. A survey samples many riders.");
    await practice.getByRole("radio", { name: "B. A city transport survey" }).check();
    await practice.getByRole("button", { name: "Check answer for question 1" }).click();
    await expect(q1.getByRole("status")).toHaveText("Correct. A survey samples many riders.");
    await expect(q1.getByRole("button", { name: "Check answer for question 1" })).toBeDisabled();

    const q2 = practice.getByRole("form", { name: "Rewrite this claim with a cited statistic." });
    await q2.getByLabel("Your answer to question 2").fill("Ridership rose 12% (City survey, 2024).");
    await q2.getByRole("button", { name: "Check answer for question 2" }).click();
    await expect(q2.getByRole("status")).toHaveText(
      "Answer recorded. This item isn't scored automatically. Model answer: Names the source; States the figure."
    );
    await expect(q2.getByRole("button", { name: "Check answer for question 2" })).toBeDisabled();
    expect(attempts).toEqual([
      { answers: [{ question_id: "q1", answer: "A" }] },
      { answers: [{ question_id: "q1", answer: "B" }] },
      { answers: [{ question_id: "q2", answer: "Ridership rose 12% (City survey, 2024)." }] },
    ]);
    await expectNoSeriousAxe(page);
    await practice.getByRole("button", { name: "Start this practice" }).click();
    await expect(practice.getByText("Thanks, your choice is saved.")).toBeVisible();
    expect(decision).toEqual({ decision: "accepted" });
  });

  test("a failed feedback run shows an error with Retry, then polls again", async ({ page }) => {
    await signIn(page, EMMA_LOOP);
    await page.route(`${api("/api/submissions")}?**`, (route) =>
      fulfill(route, 200, {
        items: [{ id: SUBMISSION_ID, person_id: EMMA.person.id, assignment_id: "a0000000-0000-4000-8000-000000000001", version: 1, status: "draft", submitted_at: "2026-10-01T11:00:00Z", feedback_status: "failed" }],
      })
    );
    let retried = false;
    await page.route(api(`/api/feedback/${SUBMISSION_ID}`), (route) =>
      fulfill(route, 200, retried ? feedback("released") : feedback("failed", { criteria: [] })));
    await page.route(api(`/api/feedback/${SUBMISSION_ID}/retry`), (route) => {
      if (route.request().method() === "POST") retried = true;
      return fulfill(route, 202, feedback("pending"));
    });
    await page.route(`${api("/api/submissions/")}*/history`, (route) => fulfill(route, 404, { detail: "Not found" }));
    await selectCourse(page);

    await page.getByRole("region", { name: "My feedback" }).getByRole("button", { name: /Version 1/ }).click();
    const dialog = page.getByRole("dialog", { name: "Feedback" });
    await expect(dialog.getByText(/Error:.*feedback could not be generated/)).toBeVisible();
    await expectNoSeriousAxe(page);
    await dialog.getByRole("button", { name: "Retry feedback" }).click();
    await expect(dialog.getByText("“Everyone I know bikes to work.”")).toBeVisible({ timeout: 15000 });
    expect(retried).toBe(true);
  });

  test("feedback awaiting release stays hidden from the student", async ({ page }) => {
    await signIn(page, EMMA_LOOP);
    await page.route(`${api("/api/submissions")}?**`, (route) =>
      fulfill(route, 200, {
        items: [{ id: SUBMISSION_ID, person_id: EMMA.person.id, assignment_id: "a0000000-0000-4000-8000-000000000001", version: 1, status: "draft", submitted_at: "2026-10-01T11:00:00Z", feedback_status: "awaiting_release" }],
      })
    );
    await page.route(api(`/api/feedback/${SUBMISSION_ID}`), (route) => fulfill(route, 200, feedback("awaiting_release")));
    await selectCourse(page);
    await page.getByRole("region", { name: "My feedback" }).getByRole("button", { name: /awaiting instructor release/ }).click();
    const dialog = page.getByRole("dialog", { name: "Feedback" });
    await expect(dialog.getByText(/Your instructor reviews this feedback before you see it/)).toBeVisible();
    await expect(dialog.getByText("Everyone I know bikes to work.", { exact: false })).toHaveCount(0);
  });

  test("the practice list opens a private set", async ({ page }) => {
    await signIn(page, EMMA_LOOP);
    await page.route(`${api("/api/submissions")}?**`, (route) => fulfill(route, 200, { items: [] }));
    await page.route(`${api("/api/ai-actions")}?**`, (route) => fulfill(route, 200, { items: [PRACTICE_ACTION] }));
    await page.route(api(`/api/ai-actions/${PRACTICE_ID}`), (route) => fulfill(route, 200, PRACTICE_ACTION));
    await selectCourse(page);
    await page.getByRole("region", { name: "My practice" }).getByRole("button", { name: /Practice set/ }).click();
    await expect(page.getByRole("dialog", { name: "Practice" }).getByText("Name one place to find transport data.")).toBeVisible();
  });
});

test.describe("ImprovementCanvas", () => {
  test("faculty grid shows Emma's evidence 2 → 3 with flags, drills into feedback, and has no practice list", async ({ page }) => {
    await signIn(page, WATSON);
    await page.route(`${api("/api/feedback/queue")}**`, (route) => fulfill(route, 200, { items: [] }));
    await page.route(api(`/api/improvement/${CS101_ID}`), (route) => fulfill(route, 200, IMPROVEMENT));
    await page.route(api(`/api/feedback/${REVISION_ID}`), (route) => fulfill(route, 200, { ...feedback("released"), submission_id: REVISION_ID }));
    await page.route(`${api("/api/submissions/")}*/history`, (route) =>
      fulfill(route, 200, {
        assignment_id: "a0000000-0000-4000-8000-000000000001",
        person_id: EMMA.person.id,
        versions: [
          { submission: { id: SUBMISSION_ID, person_id: EMMA.person.id, assignment_id: "a0000000-0000-4000-8000-000000000001", version: 1, status: "draft", submitted_at: "2026-09-20T12:00:00Z" }, criteria: [{ criterion_id: EVIDENCE, criterion_key: "evidence", score: 2, delta: null }] },
          { submission: { id: REVISION_ID, person_id: EMMA.person.id, assignment_id: "a0000000-0000-4000-8000-000000000001", version: 2, status: "draft", submitted_at: "2026-09-27T12:00:00Z" }, criteria: [{ criterion_id: EVIDENCE, criterion_key: "evidence", score: 3, delta: 1 }] },
        ],
      })
    );
    await selectCourse(page);
    await expect(page.getByRole("region", { name: "My practice" })).toHaveCount(0);
    await page.getByRole("button", { name: "Open Improvement" }).click();

    const dialog = page.getByRole("dialog", { name: "Improvement" });
    const cell = dialog.getByRole("button", { name: "2 → 3 for Emma Smith, Evidence Improving" });
    await expect(cell).toBeVisible();
    await expect(dialog.getByRole("button", { name: /3 → 3 for Emma Smith, Thesis Plateaued/ })).toBeVisible();
    await expect(dialog.getByText(/Practice attempts are private/)).toBeVisible();
    await expectNoSeriousAxe(page);

    await cell.click();
    await expect(dialog.getByRole("heading", { name: "Emma Smith · Evidence" })).toBeVisible();
    await expect(dialog.getByText("Latest change: +1.")).toBeVisible();
    await dialog.getByRole("button", { name: "View feedback for version 2" }).click();
    await expect(dialog.getByTestId("feedback-canvas")).toBeVisible();
    await expect(dialog.getByRole("table", { name: "Version history" })).toContainText("up 1");
    await expectNoSeriousAxe(page);
  });

  test("advisors see scores but cannot open criterion feedback", async ({ page }) => {
    const advisor: FakeMe = {
      ...OKAFOR,
      enrollments: [{ course_id: CS101_ID, slug: "cs101", title: "CS 101 — Intro to Computer Science", role: "observer" }],
      capabilities: { ...OKAFOR.capabilities, improvement_view: { scope: "assigned", access: "summary" } },
    };
    await signIn(page, advisor);
    const feedbackReads: string[] = [];
    await page.route(`${api("/api/feedback/")}**`, (route) => {
      feedbackReads.push(route.request().url());
      return fulfill(route, 403, { detail: "Forbidden" });
    });
    await page.route(api(`/api/improvement/${CS101_ID}`), (route) => fulfill(route, 200, IMPROVEMENT));
    await page.route(`${api("/api/roster/")}**`, (route) => fulfill(route, 200, { students: [] }));
    await selectCourse(page, 2);
    await page.getByRole("button", { name: "Open Improvement" }).click();
    const dialog = page.getByRole("dialog", { name: "Improvement" });
    await dialog.getByRole("button", { name: "2 → 3 for Emma Smith, Evidence Improving" }).click();
    await expect(dialog.getByRole("heading", { name: "Emma Smith · Evidence" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /View feedback/ })).toHaveCount(0);
    expect(feedbackReads).toEqual([]);
    await expectNoSeriousAxe(page);
  });

  test("admin gets aggregate counts, not student rows", async ({ page }) => {
    await signIn(page, HAYES_IN_COURSE);
    await page.route(api(`/api/improvement/${CS101_ID}`), (route) =>
      fulfill(route, 200, {
        ...IMPROVEMENT,
        students: [],
        aggregate: [{ criterion_id: EVIDENCE, n_students: 10, mean_delta: 0.6, flag_counts: { improving: 6, plateaued: 3, regressed: 1 } }],
      })
    );
    await page.route(`${api("/api/roster/")}**`, (route) => fulfill(route, 200, { students: [] }));
    await selectCourse(page, 2);
    await page.getByRole("button", { name: "Open Improvement" }).click();
    const dialog = page.getByRole("dialog", { name: "Improvement" });
    const row = dialog.getByRole("table", { name: "Across students" }).getByRole("row", { name: /Evidence/ });
    await expect(row).toContainText("+0.60");
    await expect(dialog.getByText("Emma Smith")).toHaveCount(0);
    await expectNoSeriousAxe(page);
  });
});
