import { expect, test } from "@playwright/test";
import { TORRES, api, fulfill } from "./fixtures/fake-api";
import { selectCourse, setupMockAPI } from "./fixtures/setup";

const SESSION_ID = "ap-session";
const TURN_ID = "ap-turn";

function approvalEvent(artifactType: string, preview: Record<string, unknown>) {
  return {
    event: "approval_request",
    session_id: SESSION_ID,
    turn_id: TURN_ID,
    sequence: 1,
    timestamp: new Date().toISOString(),
    payload: {
      approval_id: "ap-1",
      step_id: "s1",
      agent: "communication",
      action: "Send message",
      artifact_type: artifactType,
      preview,
    },
  };
}

// The shape the engine gateway sends: the call, plus the drafted artifact with free text wrapped.
const SEND_PREVIEW = {
  tool: '<user_content source="communications.send_message">communications.send_message</user_content>',
  arguments: { draft_id: "d-1" },
  artifact: {
    message: {
      draft_id: "d-1",
      channel: "inbox",
      audience: { person_ids: ["p-1", "p-2"] },
      subject: '<user_content source="communications.send_message">Chapter 5 study guide</user_content>',
      body_md: '<user_content source="communications.send_message">Hi everyone, here is a study guide.</user_content>',
    },
    recipient_count: 2,
  },
};

async function ask(page: import("@playwright/test").Page) {
  await page.getByPlaceholder(/Type a message/).fill("Send the study guide");
  await page.getByRole("button", { name: "Send" }).click();
}

test("a send_message approval shows the drafted message, not a crash", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await setupMockAPI(page, {
    me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID,
    sseEvents: [approvalEvent("message", SEND_PREVIEW)],
  });
  await page.goto("/");
  await selectCourse(page);
  await ask(page);

  const gate = page.getByRole("region", { name: "Approval needed" });
  await expect(gate.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(gate.getByText("Hi everyone, here is a study guide.")).toBeVisible();
  await expect(gate.getByText("2 recipients")).toBeVisible();
  await expect(gate.getByText(/user_content/)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a create_question approval shows the question to save", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await setupMockAPI(page, {
    me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID,
    sseEvents: [approvalEvent("quiz", {
      tool: "assessments.create_question",
      arguments: { bank_id: "b-1", stem: "Which gas is released?" },
      artifact: { question: { bank_id: "b-1", type: "mcq", stem: "Which gas is released?", options: ["Oxygen", "Nitrogen"] } },
    })],
  });
  await page.goto("/");
  await selectCourse(page);
  await ask(page);

  const gate = page.getByRole("region", { name: "Approval needed" });
  await expect(gate.getByText("Which gas is released?")).toBeVisible();
  await expect(gate.getByText("Oxygen")).toBeVisible();
  expect(errors).toEqual([]);
});

test("a grade_commit approval asks for the instructor's scores and comment, and sends them as an edit", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await setupMockAPI(page, {
    me: TORRES, sessionId: SESSION_ID, turnId: TURN_ID,
    sseEvents: [approvalEvent("grade_commit", {
      tool: "assessments.commit_grade",
      arguments: { grade_id: "g-1" },
      artifact: {
        grade: { grade_id: "g-1", submission_id: "s-1", scores: { thesis: 2, evidence: 3 },
          feedback: { thesis: "State the claim in one sentence." } },
        requires: { final_scores: ["thesis", "evidence"], holistic_md: true },
      },
    })],
  });
  let refuse = true;
  const posted: Record<string, unknown>[] = [];
  await page.route(api("/api/approval"), (route) => {
    if (route.request().method() === "OPTIONS") return fulfill(route, 204);
    posted.push(route.request().postDataJSON());
    const status = refuse ? 422 : 202;
    refuse = false;
    return fulfill(route, status,
      status === 422 ? { detail: "The final score for thesis must be a whole number." } : { status: "accepted" });
  });
  await page.goto("/");
  await selectCourse(page);
  await ask(page);

  const gate = page.getByRole("region", { name: "Approval needed" });
  await expect(gate.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(gate.getByText("(generated draft: 2)")).toBeVisible();
  await expect(page.locator("main").getByText(/^Error: /)).toHaveCount(0);

  await gate.getByRole("button", { name: "Commit with my scores" }).click();
  await expect(gate.getByRole("alert")).toContainText("Enter a whole-number final score for thesis.");
  await expect(gate.getByRole("alert")).toContainText("Write a closing comment.");
  expect(posted).toEqual([]);

  await gate.getByRole("spinbutton", { name: /thesis/ }).fill("3");
  await gate.getByRole("spinbutton", { name: /evidence/ }).fill("3");
  await gate.getByLabel("Closing comment (required)").fill("Clear claim; strong cases.");
  await gate.getByRole("button", { name: "Commit with my scores" }).click();
  await expect(gate.getByRole("alert")).toContainText("Not accepted: The final score for thesis must be a whole number.");
  await gate.getByRole("button", { name: "Commit with my scores" }).click();
  await expect.poll(() => posted.length).toBe(2);
  expect(posted[1]).toMatchObject({
    approval_id: "ap-1", decision: "edit",
    edited_payload: { grade_id: "g-1", final_scores: { thesis: 3, evidence: 3 }, holistic_md: "Clear claim; strong cases." },
  });
  expect(errors).toEqual([]);
});
