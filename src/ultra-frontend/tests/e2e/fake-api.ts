import type { BrowserContext, Page, Request, Route } from "@playwright/test";

/** Origin baked into NEXT_PUBLIC_API_URL for the smoke dev server; never resolvable. */
export const FAKE_API_ORIGIN = "http://api.smoke.test";

export const CS101_ID = "bdd640fb-0667-4ad1-9c80-317fa3b1799d";
export const MATH201_ID = "23b8c1e9-3924-46de-beb1-3b9046685257";
export const BIO150_ID = "972a8469-1641-4f82-8b9d-2434e465e150";
export const EMMA_ID = "5be6128e-18c2-4797-a142-ea7d17be3111";

export const SMOKE_CSRF = "smoke-csrf-token";

// Shape of the Me schema in contracts/api.openapi.yaml.
export interface FakeMe {
  person: { id: string; display_name: string; email: string | null };
  roles: string[];
  active_role: string;
  enrollments: { course_id: string; slug: string; title: string; role: string }[];
  advisees_count: number;
  home_route: string;
  capabilities: Record<string, { scope: string; access: string }>;
  effective_ui_policy: Record<string, unknown>;
  must_change_password: boolean;
}

const self = (access = "full") => ({ scope: "self", access });
const own = (access = "full") => ({ scope: "own", access });

export const EMMA_ME: FakeMe = {
  person: { id: EMMA_ID, display_name: "Emma Smith", email: "emma.smith@student.edu" },
  roles: ["student"],
  active_role: "student",
  enrollments: [
    { course_id: CS101_ID, slug: "cs101", title: "CS 101 — Introduction to Computer Science", role: "student" },
    { course_id: MATH201_ID, slug: "math201", title: "MATH 201 — Linear Algebra", role: "student" },
    { course_id: BIO150_ID, slug: "bio150", title: "BIO 150 — General Biology", role: "student" },
  ],
  advisees_count: 0,
  home_route: "/home",
  capabilities: {
    course_list: self("read"),
    tutor_chat: self(),
    mastery_matrix: self("read"),
    improvement_view: self("read"),
    ai_actions_log: self("read"),
    my_data: self(),
    notifications: self(),
  },
  effective_ui_policy: {},
  must_change_password: false,
};

const FACULTY_CAPS = {
  course_list: own(),
  tutor_chat: own(),
  mastery_matrix: own(),
  roster: own(),
  badge_approve: own(),
  improvement_view: own(),
  ai_review: own(),
  ai_actions_log: own("read"),
  my_data: self(),
  notifications: self(),
};

export const TORRES_ME: FakeMe = {
  person: { id: "17fc695a-07a0-4a6e-8822-e8f36c031199", display_name: "Dr. Maria Torres", email: "m.torres@university.edu" },
  roles: ["faculty", "program_lead"],
  active_role: "faculty",
  enrollments: [{ course_id: CS101_ID, slug: "cs101", title: "CS 101 — Introduction to Computer Science", role: "faculty" }],
  advisees_count: 0,
  home_route: "/",
  capabilities: FACULTY_CAPS,
  effective_ui_policy: {},
  must_change_password: false,
};

export const TORRES_PROGRAM_LEAD_ME: FakeMe = {
  ...TORRES_ME,
  active_role: "program_lead",
  home_route: "/program",
  capabilities: { course_list: { scope: "program", access: "read" }, my_data: self(), notifications: self() },
};

export const CHEN_ME: FakeMe = {
  person: { id: "6b2d6a4e-0000-4000-8000-00000000c4e4", display_name: "Dr. Sarah Chen", email: "s.chen@university.edu" },
  roles: ["faculty"],
  active_role: "faculty",
  enrollments: [{ course_id: MATH201_ID, slug: "math201", title: "MATH 201 — Linear Algebra", role: "faculty" }],
  advisees_count: 0,
  home_route: "/",
  capabilities: FACULTY_CAPS,
  effective_ui_policy: {},
  must_change_password: false,
};

export const OKAFOR_ME: FakeMe = {
  person: { id: "0a0a0a0a-0000-4000-8000-0000000000ad", display_name: "Ms. Adaeze Okafor", email: "a.okafor@university.edu" },
  roles: ["advisor"],
  active_role: "advisor",
  enrollments: [],
  advisees_count: 50,
  home_route: "/caseload",
  capabilities: {
    course_list: { scope: "assigned", access: "read" },
    roster: { scope: "assigned", access: "read" },
    mastery_matrix: { scope: "assigned", access: "read" },
    my_data: self(),
    notifications: self(),
  },
  effective_ui_policy: {},
  must_change_password: false,
};

export const ADMIN_ME: FakeMe = {
  person: { id: "0a0a0a0a-0000-4000-8000-0000000000ae", display_name: "Admin User", email: "admin@university.edu" },
  roles: ["admin"],
  active_role: "admin",
  enrollments: [],
  advisees_count: 0,
  home_route: "/",
  capabilities: {
    course_list: { scope: "all", access: "read" },
    system_settings: { scope: "all", access: "full" },
    ai_review: { scope: "all", access: "full" },
    ai_actions_log: { scope: "all", access: "read" },
    my_data: self(),
    notifications: self(),
  },
  effective_ui_policy: {},
  must_change_password: false,
};

export const SMOKE_AI_ACTION_ID = "a1a1a1a1-0000-4000-8000-0000000000a1";

// MeasurementSummary in contracts/api.openapi.yaml.
export const CS101_MEASUREMENT = {
  scope: { type: "course", id: CS101_ID, title: "CS 101 — Introduction to Computer Science" },
  from: null,
  to: "2026-10-02T00:00:00Z",
  rates: [
    { agent: "grader", action_type: "grade_draft", total: 12, accepted: 6, edited: 4, rejected: 1, other: 0, undecided: 1,
      acceptance_rate: 6 / 11, edit_rate: 4 / 11, reject_rate: 1 / 11 },
    { agent: "tutor", action_type: "criterion_feedback", total: 8, accepted: 5, edited: 2, rejected: 0, other: 1, undecided: 0,
      acceptance_rate: 5 / 8, edit_rate: 2 / 8, reject_rate: 0 },
  ],
  criterion_score_changes: [
    { criterion_id: "c0000000-0000-4000-8000-000000000001", criterion_key: "thesis", n: 4, mean_delta: 0.75 },
    { criterion_id: "c0000000-0000-4000-8000-000000000002", criterion_key: "evidence_use", n: 3, mean_delta: -0.5 },
  ],
  learning_delta_by_decision: {
    accepted: { n: 5, mean_delta: 0.6 },
    edited: { n: 3, mean_delta: 0.9 },
    rejected: { n: 0, mean_delta: null },
  },
  most_edited_criteria: [
    { criterion_id: "c0000000-0000-4000-8000-000000000001", criterion_key: "thesis", edit_count: 4, edit_rate: 0.4 },
    { criterion_id: "c0000000-0000-4000-8000-000000000002", criterion_key: "evidence_use", edit_count: 3, edit_rate: 0.3 },
  ],
  offloading: { hint_dependency_ratio: 0.25, solution_check_trips: 2 },
};

// MeasurementRollup in contracts/api.openapi.yaml.
export const INSTITUTION_ROLLUP = {
  ...CS101_MEASUREMENT,
  scope: { type: "institution", id: null, title: null },
  per_course: [
    { course: { course_id: CS101_ID, slug: "cs101", title: "CS 101 — Introduction to Computer Science" },
      totals: { total: 20, accepted: 11, edited: 6, rejected: 1, other: 1, undecided: 1, acceptance_rate: 11 / 19, edit_rate: 6 / 19, reject_rate: 1 / 19 } },
  ],
  compliance: { mismatches_count: 0 },
};

// AiAction in contracts/api.openapi.yaml.
export const SMOKE_AI_ACTION = {
  id: SMOKE_AI_ACTION_ID,
  session_id: null,
  turn_id: null,
  agent: "grader",
  action_type: "grade_draft",
  subject_person_id: EMMA_ID,
  course_id: CS101_ID,
  target_type: "grades",
  target_id: null,
  sources: [{ type: "rubric", id: "r0000000-0000-4000-8000-000000000001", version: 2, title: "Essay rubric" }],
  policies: [{ key: "grading.release_mode", value: "instructor_release", scope_type: "course", scope_id: CS101_ID, version: 1 }],
  model: "claude-test",
  prompt_sha256: null,
  output: {},
  created_at: "2026-10-01T12:00:00Z",
  decisions: [],
  outcome_links: [],
};

export const PENDING_CREDENTIAL_ID = "5d1f2c3e-8a4b-4c6d-9e0f-1a2b3c4d5e6f";
export const PYTHON_MC_ID = "6e2a3d4f-9b5c-4d7e-8f10-2b3c4d5e6f70";
export const CREDENTIAL_RECOMMENDATION_ID = "0c9a8b7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
export const INSIGHTS_UPDATE_ID = "1d0b9c8e-7f6a-4b5c-8d3e-2f1a0b9c8d7e";

// Engine-written badge recommendation (src/engine/provenance.py): target is the pending row.
export const CREDENTIAL_RECOMMENDATION = {
  ...SMOKE_AI_ACTION,
  id: CREDENTIAL_RECOMMENDATION_ID,
  agent: "learning_analyst",
  action_type: "recommendation",
  target_type: "pending_credentials",
  target_id: PENDING_CREDENTIAL_ID,
  sources: [{ type: "attestation", id: "a0000000-0000-4000-8000-000000000001", version: null, title: "Type Conversion attestation" }],
  policies: [],
  output: { kind: "credential", microcredential_id: PYTHON_MC_ID, title: "Python Fundamentals", pending_id: PENDING_CREDENTIAL_ID },
};

// An older seed-style profile_update first, so the matcher must prefer the one that wrote `insights`.
export const INSIGHTS_UPDATES = [
  {
    ...SMOKE_AI_ACTION,
    id: INSIGHTS_UPDATE_ID,
    agent: "learning_analyst",
    action_type: "profile_update",
    course_id: null,
    target_type: "persons",
    target_id: EMMA_ID,
    sources: [{ type: "session", id: "s0000000-0000-4000-8000-000000000001", version: null, title: "Tutoring session, 28 Sep" }],
    policies: [],
    output: { tool: "roster.update_student_insights", insights: ["You learn fastest from worked examples."] },
  },
  {
    ...SMOKE_AI_ACTION,
    id: "2e1c0d9f-8a7b-4c6d-9e4f-3a2b1c0d9e8f",
    agent: "learning_analyst",
    action_type: "profile_update",
    target_type: null,
    sources: [],
    policies: [],
    output: { strengths: ["Variables"], focus: ["Loops"] },
  },
];

// Same shape graph.mastery_map returns (src/data_mcp/mcp_servers/content/tools.py).
export const EMMA_CS101_MASTERY = {
  student_name: "Emma Smith",
  course_title: "CS 101 — Introduction to Computer Science",
  microcredentials: [
    {
      id: "6f1c1f7e-0000-4000-8000-000000000001",
      title: "Programming Fundamentals",
      earned: false,
      progress: { mastery: 1, proficient: 1, emerging: 1, not_started: 0 },
      total_concepts: 3,
      modules: [
        {
          id: "6f1c1f7e-0000-4000-8000-000000000011",
          title: "Module 1: Variables and Types",
          concepts: [
            { id: "6f1c1f7e-0000-4000-8000-000000000101", title: "Variables and Assignment", level: "mastery" },
            { id: "6f1c1f7e-0000-4000-8000-000000000102", title: "Primitive Data Types", level: "proficient" },
            { id: "6f1c1f7e-0000-4000-8000-000000000103", title: "Type Conversion", level: "emerging" },
          ],
        },
      ],
    },
    {
      id: "6f1c1f7e-0000-4000-8000-000000000002",
      title: "Control Flow",
      earned: false,
      progress: { mastery: 0, proficient: 0, emerging: 0, not_started: 1 },
      total_concepts: 1,
      modules: [
        {
          id: "6f1c1f7e-0000-4000-8000-000000000021",
          title: "Module 2: Conditionals",
          concepts: [
            { id: "6f1c1f7e-0000-4000-8000-000000000201", title: "If Statements", level: "not_started" },
          ],
        },
      ],
    },
  ],
  summary: {
    total_concepts: 4,
    mastery: 1,
    proficient: 1,
    emerging: 1,
    not_started: 1,
    microcredentials_earned: 0,
    microcredentials_total: 2,
  },
};

/** Sets the cookies the engine's /api/auth/login would; both UIs share them because cookies ignore ports. */
export async function setSessionCookies(context: BrowserContext, baseURL: string): Promise<void> {
  const url = new URL(baseURL);
  await context.addCookies([
    { name: "lms_session", value: "smoke-session-token", domain: url.hostname, path: "/", httpOnly: true, sameSite: "Lax" },
    { name: "lms_csrf", value: SMOKE_CSRF, domain: url.hostname, path: "/", sameSite: "Lax" },
  ]);
}

export interface RecordedRequest {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface FakeEngine {
  /** Requests that matched no handler; specs assert this stays empty. */
  unhandled: string[];
  /** Every non-OPTIONS request, in order. */
  requests: RecordedRequest[];
  /** The /me the fake currently serves; null answers 401. */
  me: FakeMe | null;
  /** Per-path status overrides, e.g. {"GET /api/roster/<id>": 403}. */
  statusOverrides: Record<string, number>;
  /** Called on a successful POST /api/auth/login, before the response is sent. */
  onLogin?: () => Promise<void>;
  /** username -> /me returned by POST /api/auth/login; anything else is a 401. */
  accounts: Record<string, { password: string; me: FakeMe }>;
}

export function corsHeaders(req: Request): Record<string, string> {
  return {
    "access-control-allow-origin": req.headers()["origin"] ?? "*",
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "access-control-allow-headers": "content-type, x-csrf-token",
  };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers: corsHeaders(route.request()),
    body: JSON.stringify(body),
  });
}

function sse(route: Route, events: unknown[]) {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  return route.fulfill({ status: 200, contentType: "text/event-stream", headers: corsHeaders(route.request()), body });
}

function parseBody(req: Request): unknown {
  const raw = req.postData();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

/** Routes every request to FAKE_API_ORIGIN through canned engine responses. */
export async function mockEngine(page: Page, opts: Partial<Pick<FakeEngine, "me" | "accounts" | "onLogin">> = {}): Promise<FakeEngine> {
  const engine: FakeEngine = {
    unhandled: [],
    requests: [],
    me: opts.me === undefined ? EMMA_ME : opts.me,
    statusOverrides: {},
    accounts: opts.accounts ?? {},
    onLogin: opts.onLogin,
  };

  await page.route(`${FAKE_API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();

    if (method === "OPTIONS") {
      return route.fulfill({ status: 204, headers: corsHeaders(req) });
    }

    const body = parseBody(req);
    engine.requests.push({ method, path, headers: req.headers(), body });

    const override = engine.statusOverrides[`${method} ${path}`];
    if (override) return json(route, { detail: "overridden" }, override);

    if (method === "POST" && path === "/api/auth/login") {
      const { username, password } = body as { username: string; password: string };
      const account = engine.accounts[username.toLowerCase()];
      if (!account || account.password !== password) {
        return json(route, { detail: "Invalid username or password." }, 401);
      }
      engine.me = account.me;
      await engine.onLogin?.();
      return json(route, account.me);
    }

    if (method === "GET" && path === "/api/auth/me") {
      return engine.me ? json(route, engine.me) : json(route, { detail: "Not authenticated" }, 401);
    }

    if (!engine.me) return json(route, { detail: "Not authenticated" }, 401);
    const me = engine.me;

    if (method === "POST" && path === "/api/auth/role") {
      const { role } = body as { role: string };
      if (!me.roles.includes(role)) return json(route, { detail: "Role not held" }, 403);
      engine.me = role === "program_lead" && me.person.id === TORRES_ME.person.id ? TORRES_PROGRAM_LEAD_ME : { ...me, active_role: role };
      return json(route, engine.me);
    }

    if (method === "POST" && path === "/api/auth/logout") {
      engine.me = null;
      return route.fulfill({ status: 204, headers: corsHeaders(req) });
    }

    // Shape of CreateSessionResponse (src/engine/api/session.py).
    if (method === "POST" && path === "/api/session") {
      const { course_id } = body as { course_id: string };
      const sessionId = `smoke-session-${me.active_role}`;
      const briefTurnId = `brief-${sessionId}`;
      return json(
        route,
        {
          session_id: sessionId,
          person_id: me.person.id,
          course_uuid: course_id,
          brief_turn_id: briefTurnId,
          stream_url: `/api/stream?session_id=${sessionId}&turn_id=${briefTurnId}`,
        },
        201,
      );
    }

    if (method === "POST" && path === "/api/converse") {
      const { session_id } = body as { session_id: string };
      return json(route, { turn_id: "smoke-turn-1", stream_url: `/api/stream?session_id=${session_id}&turn_id=smoke-turn-1` }, 202);
    }

    if (method === "GET" && path === "/api/stream") {
      if (url.searchParams.get("turn_id") === "smoke-turn-1") {
        return sse(route, [
          { event: "agent_start", payload: { step_id: "s1", agent: "tutor", inputs: {} } },
          { event: "agent_tool_call", payload: { step_id: "s1", agent: "tutor", tool: "content.retrieve", arguments: {}, result_summary: "2 items", latency_ms: 5, success: true } },
          { event: "agent_token", payload: { step_id: "s1", agent: "tutor", delta: "Here is", channel: "response" } },
          { event: "final", payload: { answer_markdown: "Here is your smoke-test answer.", artifacts: [], cost_usd: 0, tokens: 0, wall_time_ms: 1 } },
        ]);
      }
      return sse(route, []);
    }

    if (method === "GET" && path === `/api/measurement/courses/${CS101_ID}`) {
      return json(route, CS101_MEASUREMENT);
    }

    if (method === "GET" && path === "/api/measurement/rollup") {
      return json(route, INSTITUTION_ROLLUP);
    }

    if (method === "GET" && path === "/api/measurement/export") {
      const format = url.searchParams.get("format") ?? "json";
      const table = url.searchParams.get("table") ?? "ai_actions";
      const filename = format === "csv" ? `${table}.csv` : "measurement.json";
      const body = format === "csv"
        ? "id,agent,action_type\n" + `${SMOKE_AI_ACTION_ID},grader,grade_draft\n`
        : JSON.stringify({ course_id: url.searchParams.get("course_id"), from: null, to: "2026-10-02T00:00:00Z", ai_actions: [SMOKE_AI_ACTION], human_decisions: [], outcome_links: [] });
      return route.fulfill({
        status: 200,
        contentType: format === "csv" ? "text/csv" : "application/json",
        headers: {
          ...corsHeaders(req),
          "content-disposition": `attachment; filename="${filename}"`,
          "access-control-expose-headers": "content-disposition",
        },
        body,
      });
    }

    if (method === "GET" && path === "/api/ai-actions") {
      const actionType = url.searchParams.get("action_type");
      const subject = url.searchParams.get("subject_person_id");
      const items = actionType === "recommendation"
        ? [CREDENTIAL_RECOMMENDATION].filter((a) => !subject || a.subject_person_id === subject)
        : actionType === "profile_update"
          ? INSIGHTS_UPDATES.filter((a) => !subject || a.subject_person_id === subject)
          : [SMOKE_AI_ACTION];
      return json(route, { items, next_cursor: null });
    }

    const aiAction = [SMOKE_AI_ACTION, CREDENTIAL_RECOMMENDATION, ...INSIGHTS_UPDATES].find((a) => path === `/api/ai-actions/${a.id}`);
    if (method === "GET" && aiAction) {
      return json(route, aiAction);
    }

    if (method === "GET" && path === `/api/pending-credentials/${CS101_ID}`) {
      return json(route, {
        pending: [
          {
            id: PENDING_CREDENTIAL_ID,
            person_id: EMMA_ID,
            student_name: "Emma Smith",
            microcredential_id: PYTHON_MC_ID,
            credential_title: "Python Fundamentals",
            created_at: "2026-09-20T12:00:00+00:00",
          },
        ],
      });
    }

    if (method === "GET" && path === `/api/mastery/${EMMA_ID}/${CS101_ID}`) {
      return json(route, EMMA_CS101_MASTERY);
    }

    if (method === "GET" && path.startsWith("/api/roster/")) {
      return json(route, { students: [], total: 0 });
    }

    if (method === "GET" && path === `/api/student-insights/${EMMA_ID}`) {
      return json(route, { insights: ["You learn fastest from worked examples."] });
    }

    if (method === "GET" && path === `/api/student-goals/${EMMA_ID}`) {
      return json(route, {
        goals: [
          {
            description: "Master Type Conversion before the midterm",
            target_date: "2026-10-20",
            created_at: "2026-09-15T12:00:00+00:00",
            status: "active",
          },
        ],
      });
    }

    engine.unhandled.push(`${method} ${path}${url.search}`);
    return json(route, { detail: "not mocked" }, 404);
  });

  return engine;
}
