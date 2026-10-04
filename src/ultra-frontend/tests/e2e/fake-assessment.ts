import { CS101_ID, EMMA_ID } from "./ids";

// Contract-shaped payloads for the formative loop (api.openapi.yaml tag "assessment") and the
// admin access log.

export const ESSAY_ID = "e55a7000-0000-4000-8000-000000000e01";
export const ESSAY_TITLE = "Transit policy essay";
export const DRAFT1_ID = "d1000000-0000-4000-8000-0000000000d1";
export const DRAFT2_ID = "d2000000-0000-4000-8000-0000000000d2";
export const PRACTICE_ID = "f1000000-0000-4000-8000-0000000000f1";
export const QUEUED_SUBMISSION_ID = "d3000000-0000-4000-8000-0000000000d3";
export const FINAL_SUBMISSION_ID = "d4000000-0000-4000-8000-0000000000d4";
export const LIAM_ID = "11a00000-0000-4000-8000-0000000011a0";
export const NOAH_ID = "22b00000-0000-4000-8000-0000000022b0";
export const THESIS_ID = "c1000000-0000-4000-8000-0000000000c1";
export const EVIDENCE_ID = "c2000000-0000-4000-8000-0000000000c2";
export const FEEDBACK_ACTION_ID = "fa000000-0000-4000-8000-0000000000fa";
export const PRACTICE_Q1_ID = "9e000000-0000-4000-8000-0000000000e1";
export const PRACTICE_Q2_ID = "9e000000-0000-4000-8000-0000000000e2";

const criterion = (id: string, key: string, description: string, score: number, label: string, extra: Record<string, unknown> = {}) => ({
  criterion_id: id,
  criterion_key: key,
  description,
  ai_score: score,
  level_label: label,
  ai_rationale: `The ${key} is at the ${label.toLowerCase()} level.`,
  evidence_spans: [{ quote: key === "thesis" ? "Cities should fund transit first" : "many people say buses are good", start: 0, end: 30 }],
  next_step: key === "thesis" ? "Name the trade-off your thesis accepts." : "Cite one study with a number for each claim.",
  final_score: null,
  ai_action_id: FEEDBACK_ACTION_ID,
  released_at: "2026-09-20T12:05:00Z",
  ...extra,
});

export function submission(id: string, version: number, status: "draft" | "final", personId = EMMA_ID, extra: Record<string, unknown> = {}) {
  return {
    id,
    person_id: personId,
    assignment_id: ESSAY_ID,
    assignment_title: ESSAY_TITLE,
    course_id: CS101_ID,
    version,
    parent_id: null,
    status,
    body_md: `Essay text, version ${version}. Cities should fund transit first because many people say buses are good.`,
    attachments: [],
    submitted_at: `2026-09-2${version}T12:00:00Z`,
    feedback_status: "released",
    ...extra,
  };
}

export const DRAFT1 = submission(DRAFT1_ID, 1, "draft");
export const DRAFT2 = submission(DRAFT2_ID, 2, "draft", EMMA_ID, { parent_id: DRAFT1_ID, feedback_status: "pending" });

export const DRAFT1_FEEDBACK = {
  submission_id: DRAFT1_ID,
  assignment_id: ESSAY_ID,
  person_id: EMMA_ID,
  student_name: "Emma Smith",
  status: "released",
  release_mode: "auto",
  criteria: [
    criterion(THESIS_ID, "thesis", "States a clear, arguable claim.", 3, "Proficient"),
    criterion(EVIDENCE_ID, "evidence", "Supports claims with specific evidence.", 2, "Developing"),
  ],
  practice_set_ai_action_id: null,
};

export const DRAFT2_FEEDBACK = {
  ...DRAFT1_FEEDBACK,
  submission_id: DRAFT2_ID,
  criteria: [
    criterion(THESIS_ID, "thesis", "States a clear, arguable claim.", 3, "Proficient"),
    criterion(EVIDENCE_ID, "evidence", "Supports claims with specific evidence.", 3, "Proficient"),
  ],
  practice_set_ai_action_id: PRACTICE_ID,
};

export const HISTORY_V2 = {
  assignment_id: ESSAY_ID,
  person_id: EMMA_ID,
  versions: [
    { submission: DRAFT1, criteria: [
      { criterion_id: THESIS_ID, criterion_key: "thesis", score: 3, delta: null },
      { criterion_id: EVIDENCE_ID, criterion_key: "evidence", score: 2, delta: null },
    ] },
    { submission: { ...DRAFT2, feedback_status: "released" }, criteria: [
      { criterion_id: THESIS_ID, criterion_key: "thesis", score: 3, delta: 0 },
      { criterion_id: EVIDENCE_ID, criterion_key: "evidence", score: 3, delta: 1 },
    ] },
  ],
};

export const PRACTICE_ACTION = {
  id: PRACTICE_ID,
  session_id: null,
  turn_id: null,
  agent: "content_generator",
  action_type: "practice_item",
  subject_person_id: EMMA_ID,
  course_id: CS101_ID,
  target_type: "questions",
  target_id: null,
  sources: [{ type: "rubric", id: "r0000000-0000-4000-8000-000000000001", version: 1, title: "Essay rubric: evidence" }],
  policies: [],
  model: "claude-test",
  prompt_sha256: null,
  output: {
    criterion_key: "evidence",
    question_ids: [PRACTICE_Q1_ID, PRACTICE_Q2_ID],
    items: [
      { type: "mcq", stem: "Which sentence gives specific evidence?", options: { A: "Buses are good.", B: "Ridership rose 12% in 2024." },
        answer_key: { correct: "B", explanation: "A figure with a year is specific evidence." } },
      { type: "short_answer", stem: "Rewrite this claim with a cited figure: 'many people ride buses'." },
    ],
  },
  created_at: "2026-09-22T12:10:00Z",
  decisions: [],
  outcome_links: [],
};

export const QUEUED_FEEDBACK = {
  submission_id: QUEUED_SUBMISSION_ID,
  assignment_id: ESSAY_ID,
  person_id: LIAM_ID,
  student_name: "Liam Chen",
  status: "awaiting_release",
  release_mode: "instructor_release",
  criteria: [
    criterion(THESIS_ID, "thesis", "States a clear, arguable claim.", 2, "Developing", { released_at: null }),
    criterion(EVIDENCE_ID, "evidence", "Supports claims with specific evidence.", 1, "Beginning", { released_at: null }),
  ],
  practice_set_ai_action_id: null,
};

export const FINAL_SUBMISSION = submission(FINAL_SUBMISSION_ID, 3, "final", NOAH_ID, { feedback_status: "none" });

export const FINAL_FEEDBACK = {
  submission_id: FINAL_SUBMISSION_ID,
  assignment_id: ESSAY_ID,
  person_id: NOAH_ID,
  student_name: "Noah Patel",
  status: "none",
  release_mode: "instructor_release",
  criteria: [
    criterion(THESIS_ID, "thesis", "States a clear, arguable claim.", 3, "Proficient", { released_at: null }),
    criterion(EVIDENCE_ID, "evidence", "Supports claims with specific evidence.", 2, "Developing", { released_at: null }),
  ],
  practice_set_ai_action_id: null,
};

const point = (id: string, version: number, status: string, score: number) =>
  ({ submission_id: id, version, status, score, submitted_at: `2026-09-2${version}T12:00:00Z` });

export const CS101_IMPROVEMENT = {
  course_id: CS101_ID,
  criteria: [
    { criterion_id: THESIS_ID, criterion_key: "thesis", description: "States a clear, arguable claim.", target_score: 3 },
    { criterion_id: EVIDENCE_ID, criterion_key: "evidence", description: "Supports claims with specific evidence.", target_score: 3 },
  ],
  students: [
    {
      student_id: EMMA_ID,
      display_name: "Emma Smith",
      trajectories: [
        { criterion_id: THESIS_ID, points: [point(DRAFT1_ID, 1, "draft", 3), point(DRAFT2_ID, 2, "draft", 3)], latest_delta: 0, flag: "ready_for_summative" },
        { criterion_id: EVIDENCE_ID, points: [point(DRAFT1_ID, 1, "draft", 2), point(DRAFT2_ID, 2, "draft", 3)], latest_delta: 1, flag: "improving" },
      ],
    },
    {
      student_id: LIAM_ID,
      display_name: "Liam Chen",
      trajectories: [
        { criterion_id: THESIS_ID, points: [point(QUEUED_SUBMISSION_ID, 1, "draft", 2), point(QUEUED_SUBMISSION_ID.replace("d3", "d5"), 2, "draft", 2)], latest_delta: 0, flag: "plateaued" },
        { criterion_id: EVIDENCE_ID, points: [point(QUEUED_SUBMISSION_ID, 1, "draft", 2), point(QUEUED_SUBMISSION_ID.replace("d3", "d5"), 2, "draft", 1)], latest_delta: -1, flag: "regressed" },
      ],
    },
  ],
  aggregate: [
    { criterion_id: THESIS_ID, n_students: 2, mean_delta: 0, flag_counts: { plateaued: 1, ready_for_summative: 1 } },
    { criterion_id: EVIDENCE_ID, n_students: 2, mean_delta: 0, flag_counts: { improving: 1, regressed: 1 } },
  ],
};

export const ACCESS_LOG_PAGE_1 = {
  entries: [
    { id: "a1", actor: { id: "17fc695a-07a0-4a6e-8822-e8f36c031199", display_name: "Dr. Maria Torres" }, subject_id: EMMA_ID,
      resource: "analyst_summary", resource_id: null, purpose: "course roster review", created_at: "2026-09-30T15:00:00Z" },
    { id: "a2", actor: { id: "17fc695a-07a0-4a6e-8822-e8f36c031199", display_name: "Dr. Maria Torres" }, subject_id: EMMA_ID,
      resource: "submission", resource_id: DRAFT1_ID, purpose: null, created_at: "2026-09-29T15:00:00Z" },
  ],
  next_before: "2026-09-29T15:00:00Z",
};

export const ACCESS_LOG_PAGE_2 = {
  entries: [
    { id: "a3", actor: { id: "0a0a0a0a-0000-4000-8000-0000000000ad", display_name: "Ms. Adaeze Okafor" }, subject_id: EMMA_ID,
      resource: "transcript", resource_id: "s1", purpose: "advising", created_at: "2026-09-01T09:00:00Z" },
  ],
  next_before: null,
};

export interface AssessmentState {
  /** Emma's versions on the essay, oldest first. */
  versions: Record<string, unknown>[];
  /** GETs of a new draft's feedback answered `pending` before it is released. */
  pendingPolls: number;
  /** Draft 2's feedback run fails until POST /api/feedback/{id}/retry. */
  failDraft2: boolean;
  feedbackGets: Record<string, number>;
  queue: Record<string, unknown>[];
  finals: { submission: Record<string, unknown>; feedback: Record<string, unknown> }[];
  pendingCredentials: Record<string, unknown>[];
  /** Bodies of POST /api/practice/{id}/attempts, in order. */
  practiceAttempts: Record<string, unknown>[];
  /** Bodies of POST /api/assignments/{node}/alignment/decisions, with the node. */
  alignmentDecisions: { assignmentNode: string; body: unknown }[];
}

export function newAssessmentState(): AssessmentState {
  return {
    versions: [DRAFT1],
    pendingPolls: 1,
    failDraft2: false,
    feedbackGets: {},
    queue: [QUEUED_FEEDBACK],
    finals: [{ submission: FINAL_SUBMISSION, feedback: FINAL_FEEDBACK }],
    pendingCredentials: [],
    practiceAttempts: [],
    alignmentDecisions: [],
  };
}

export interface FakeResponse { status: number; body: unknown }

const ok = (body: unknown, status = 200): FakeResponse => ({ status, body });

/** Answers the assessment, practice and access-log routes; null means not handled here. */
export function handleAssessment(state: AssessmentState, role: string, method: string, path: string, url: URL, body: unknown): FakeResponse | null {
  if (method === "GET" && path === "/api/submissions") {
    if (role === "student") {
      const all = url.searchParams.get("all_versions") === "true";
      return ok({ items: all ? state.versions : state.versions.slice(-1), next_cursor: null });
    }
    return ok({ items: state.finals.map((f) => f.submission), next_cursor: null });
  }

  if (method === "POST" && path === "/api/submissions") {
    const req = body as { assignment_id: string; status: "draft" | "final"; body_md: string; parent_id: string | null };
    const latest = state.versions.at(-1) as { id: string; version: number; status: string } | undefined;
    if (latest?.status === "final") return ok({ detail: "A final version already exists." }, 409);
    if (latest && req.parent_id !== latest.id) return ok({ detail: "parent_id is not the latest version." }, 409);
    const created = { ...DRAFT2, version: (latest?.version ?? 0) + 1, status: req.status, body_md: req.body_md, parent_id: req.parent_id,
      feedback_status: req.status === "final" ? "none" : "pending" };
    state.versions.push(created);
    return ok(created, 201);
  }

  const submissionMatch = /^\/api\/submissions\/([^/]+)(\/history)?$/.exec(path);
  if (method === "GET" && submissionMatch) {
    const [, id, history] = submissionMatch;
    if (history) return ok(id === DRAFT2_ID ? HISTORY_V2 : { ...HISTORY_V2, versions: HISTORY_V2.versions.slice(0, 1) });
    const found = [...state.versions, ...state.finals.map((f) => f.submission), { ...DRAFT1, id: QUEUED_SUBMISSION_ID, person_id: LIAM_ID }]
      .find((s) => s.id === id);
    return found ? ok(found) : ok({ detail: "Not found" }, 404);
  }

  if (method === "GET" && path === "/api/feedback/queue") {
    return ok({ items: state.queue, next_cursor: null });
  }

  const releaseMatch = /^\/api\/feedback\/([^/]+)\/release$/.exec(path);
  if (method === "POST" && releaseMatch) {
    const queued = state.queue.find((q) => q.submission_id === releaseMatch[1]);
    if (!queued) return ok({ detail: "Already released or suppressed" }, 409);
    state.queue = state.queue.filter((q) => q !== queued);
    const action = (body as { action: string }).action;
    return ok({ ...queued, status: action === "release" ? "released" : "suppressed" });
  }

  const retryMatch = /^\/api\/feedback\/([^/]+)\/retry$/.exec(path);
  if (method === "POST" && retryMatch) {
    if (retryMatch[1] !== DRAFT2_ID || !state.failDraft2) return ok({ detail: "Feedback has not failed." }, 409);
    state.failDraft2 = false;
    state.feedbackGets[DRAFT2_ID] = 0;
    return ok({ ...DRAFT2_FEEDBACK, status: "pending", criteria: [], practice_set_ai_action_id: null }, 202);
  }

  const feedbackMatch = /^\/api\/feedback\/([^/]+)$/.exec(path);
  if (method === "GET" && feedbackMatch) {
    if (role === "advisor") return ok({ detail: "Forbidden" }, 403);
    const id = feedbackMatch[1];
    if (id === DRAFT1_ID) return ok(DRAFT1_FEEDBACK);
    if (id === DRAFT2_ID && state.failDraft2) {
      return ok({ ...DRAFT2_FEEDBACK, status: "failed", criteria: [], practice_set_ai_action_id: null });
    }
    if (id === DRAFT2_ID) {
      const n = (state.feedbackGets[id] = (state.feedbackGets[id] ?? 0) + 1);
      return n <= state.pendingPolls ? ok({ ...DRAFT2_FEEDBACK, status: "pending", criteria: [], practice_set_ai_action_id: null }) : ok(DRAFT2_FEEDBACK);
    }
    const final = state.finals.find((f) => f.submission.id === id);
    if (final) return ok(final.feedback);
    if (id === QUEUED_SUBMISSION_ID) return ok(QUEUED_FEEDBACK);
    return ok({ submission_id: id, status: "released", release_mode: "auto", criteria: [], practice_set_ai_action_id: null });
  }

  const attemptMatch = /^\/api\/practice\/([^/]+)\/attempts$/.exec(path);
  if (method === "POST" && attemptMatch) {
    if (role !== "student") return ok({ detail: "Forbidden" }, 403);
    if (attemptMatch[1] !== PRACTICE_ID) return ok({ detail: "Not found" }, 404);
    const { answers } = body as { answers: { question_id: string; answer: string }[] };
    state.practiceAttempts.push(body as Record<string, unknown>);
    const results = answers.map(({ question_id, answer }) => question_id === PRACTICE_Q1_ID
      ? { question_id, correct: answer.trim().toLowerCase() === "b",
          expected: "B", feedback: "A figure with a year is specific evidence." }
      : { question_id, correct: null, expected: "Names the source; States the figure", feedback: null });
    return ok({ practice_set_id: PRACTICE_ID, attempt_id: `att-${state.practiceAttempts.length}`,
      correct: results.filter((r) => r.correct === true).length, total: results.length, results }, 201);
  }

  const alignmentMatch = /^\/api\/assignments\/([^/]+)\/alignment\/decisions$/.exec(path);
  if (method === "POST" && alignmentMatch) {
    if (role !== "faculty") return ok({ detail: "Forbidden" }, 403);
    state.alignmentDecisions.push({ assignmentNode: decodeURIComponent(alignmentMatch[1]), body });
    const { decisions } = body as { decisions: { key: string; decision: string }[] };
    const kept = decisions.filter((d) => d.decision !== "reject");
    return ok({
      ai_action_id: "aa000000-0000-4000-8000-0000000000a1",
      rubric_id: kept.length ? "r0000000-0000-4000-8000-000000000001" : null,
      criterion_ids: kept.map((_, i) => `c${i + 1}`),
      decisions: decisions.map((d) => ({ criterion_key: d.key, decision: `${d.decision}ed`.replace("eed", "ed") })),
    }, 201);
  }

  if (method === "GET" && path === `/api/improvement/${CS101_ID}`) {
    if (role === "admin" || role === "program_lead") return ok({ ...CS101_IMPROVEMENT, students: [] });
    return ok(CS101_IMPROVEMENT);
  }

  if (method === "GET" && path === `/api/ai-actions/${PRACTICE_ID}`) return ok(PRACTICE_ACTION);
  if (method === "GET" && path === `/api/ai-actions/${FEEDBACK_ACTION_ID}`) {
    return ok({ ...PRACTICE_ACTION, id: FEEDBACK_ACTION_ID, agent: "feedback", action_type: "criterion_feedback", output: {} });
  }
  if (method === "POST" && path === `/api/ai-actions/${PRACTICE_ID}/decisions`) {
    const decision = (body as { decision: string }).decision;
    return ok({ id: "hd1", ai_action_id: PRACTICE_ID, decided_by: EMMA_ID, decision, decided_at: "2026-10-02T00:00:00Z" }, 201);
  }

  if (method === "GET" && path === "/api/access-log") {
    return ok(url.searchParams.get("before") ? ACCESS_LOG_PAGE_2 : ACCESS_LOG_PAGE_1);
  }

  const credentialMatch = /^\/api\/(approve|reject)-credential\/([^/]+)$/.exec(path);
  if (method === "POST" && credentialMatch) {
    return ok(credentialMatch[1] === "approve" ? { success: true, credential_id: "cred-1" } : { rejected: true, pending_id: credentialMatch[2] });
  }

  return null;
}
