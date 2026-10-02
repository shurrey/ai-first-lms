import type { BrowserContext, Page, Request, Route } from "@playwright/test";

/** Origin baked into NEXT_PUBLIC_API_URL for the mocked dev server; never resolvable. */
export const FAKE_API_ORIGIN = "http://api.chat-smoke.test";
export const E2E_PORT = Number(process.env.E2E_PORT ?? 3120);
export const UI_ORIGIN = `http://localhost:${E2E_PORT}`;
export const CSRF_TOKEN = "smoke-csrf-token";

export const CS101_ID = "bdd640fb-0667-4ad1-9c80-317fa3b1799d";
export const MATH201_ID = "23b8c1e9-3924-46de-beb1-3b9046685257";

type Role = "student" | "faculty" | "program_lead" | "advisor" | "admin";

export interface FakeMe {
  person: { id: string; display_name: string; email: string | null };
  roles: Role[];
  active_role: Role;
  enrollments: Array<{ course_id: string; slug: string; title: string; role: string }>;
  advisees_count: number;
  home_route: string;
  capabilities: Record<string, { scope: string; access: string }>;
  effective_ui_policy: Record<string, unknown>;
  must_change_password: boolean;
}

const self = (access = "full") => ({ scope: "self", access });
const own = (access = "full") => ({ scope: "own", access });

export const EMMA: FakeMe = {
  person: { id: "5be6128e-18c2-4797-a142-ea7d17be3111", display_name: "Emma Smith", email: "emma.smith@student.edu" },
  roles: ["student"],
  active_role: "student",
  enrollments: [
    { course_id: CS101_ID, slug: "cs101", title: "CS 101 — Intro to Computer Science", role: "student" },
    { course_id: MATH201_ID, slug: "math201", title: "MATH 201 — Linear Algebra", role: "student" },
  ],
  advisees_count: 0,
  home_route: "/",
  capabilities: {
    course_list: self("read"),
    tutor_chat: self(),
    content_generation: self(),
    mastery_matrix: self("read"),
    my_data: self(),
    notifications: self(),
  },
  effective_ui_policy: {},
  must_change_password: false,
};

const TORRES_FACULTY_CAPS = {
  course_list: own("read"),
  tutor_chat: own(),
  content_generation: own(),
  roster: own(),
  badge_approve: own(),
  mastery_matrix: own(),
  my_data: self(),
  notifications: self(),
};

export const TORRES: FakeMe = {
  person: { id: "7a1c0000-0000-4000-8000-000000000001", display_name: "Dr. Maria Torres", email: "m.torres@university.edu" },
  roles: ["faculty", "program_lead"],
  active_role: "faculty",
  enrollments: [
    { course_id: CS101_ID, slug: "cs101", title: "CS 101 — Intro to Computer Science", role: "faculty" },
  ],
  advisees_count: 0,
  home_route: "/teaching",
  capabilities: TORRES_FACULTY_CAPS,
  effective_ui_policy: {},
  must_change_password: false,
};

export const TORRES_AS_PROGRAM_LEAD: FakeMe = {
  ...TORRES,
  active_role: "program_lead",
  home_route: "/program",
  capabilities: {
    course_list: { scope: "program", access: "read" },
    roster: { scope: "program", access: "aggregate" },
    my_data: self(),
    notifications: self(),
  },
};

export const OKAFOR: FakeMe = {
  person: { id: "0a7a0000-0000-4000-8000-000000000001", display_name: "Ms. Adaeze Okafor", email: "a.okafor@university.edu" },
  roles: ["advisor"],
  active_role: "advisor",
  enrollments: [],
  advisees_count: 50,
  home_route: "/",
  capabilities: {
    course_list: { scope: "assigned", access: "read" },
    roster: { scope: "assigned", access: "read" },
    my_data: self(),
    notifications: self(),
  },
  effective_ui_policy: {},
  must_change_password: false,
};

export const HAYES: FakeMe = {
  person: { id: "4a7e0000-0000-4000-8000-000000000001", display_name: "Dr. Richard Hayes", email: "r.hayes@university.edu" },
  roles: ["admin"],
  active_role: "admin",
  enrollments: [],
  advisees_count: 0,
  home_route: "/",
  capabilities: {
    course_list: { scope: "all", access: "read" },
    roster: { scope: "all", access: "full" },
    system_settings: { scope: "all", access: "full" },
    my_data: self(),
    notifications: self(),
  },
  effective_ui_policy: {},
  must_change_password: false,
};

// Credentialed CORS: the origin must be echoed exactly, never "*".
const CORS_HEADERS = {
  "access-control-allow-origin": UI_ORIGIN,
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "access-control-allow-headers": "content-type, x-csrf-token, accept",
};

/** Answers the CORS preflight, then fulfils with JSON (or an empty body when `body` is undefined). */
export async function fulfill(route: Route, status: number, body?: unknown) {
  if (route.request().method() === "OPTIONS") {
    await route.fulfill({ status: 204, headers: CORS_HEADERS });
    return;
  }
  await route.fulfill({
    status,
    headers: { ...CORS_HEADERS, ...(body !== undefined && { "content-type": "application/json" }) },
    body: body === undefined ? "" : JSON.stringify(body),
  });
}

export function api(path: string): string {
  return `${FAKE_API_ORIGIN}${path}`;
}

/** The cookies the orchestrator would set on host localhost after a successful login. */
export async function setSessionCookies(context: BrowserContext) {
  await context.addCookies([
    { name: "lms_session", value: "smoke-session", url: UI_ORIGIN, httpOnly: true, sameSite: "Lax" },
    { name: "lms_csrf", value: CSRF_TOKEN, url: UI_ORIGIN, sameSite: "Lax" },
  ]);
}

export interface AuthMock {
  /** Requests seen by the fake API, excluding CORS preflights. */
  requests: Request[];
  current: () => FakeMe | null;
}

/**
 * Routes /api/auth/* on the fake API. `me: null` means signed out (401).
 * Login accepts `password === "correct horse battery"` and signs in as `loginAs`.
 * Role switch returns `roleSwitch[role]` when given, else 403.
 */
export async function mockAuth(
  page: Page,
  options: {
    me: FakeMe | null;
    loginAs?: FakeMe;
    roleSwitch?: Partial<Record<Role, FakeMe>>;
    signedIn?: boolean;
  }
): Promise<AuthMock> {
  let me = options.me;
  const requests: Request[] = [];
  page.on("request", (r) => {
    if (r.url().startsWith(FAKE_API_ORIGIN) && r.method() !== "OPTIONS") requests.push(r);
  });
  if (options.signedIn ?? me !== null) await setSessionCookies(page.context());

  // Registered first so every more specific route below (and in the spec) wins.
  await page.route(`${FAKE_API_ORIGIN}/**`, (route) => fulfill(route, 404, { detail: "Not mocked" }));

  await page.route(api("/api/auth/me"), (route) => (me ? fulfill(route, 200, me) : fulfill(route, 401, { detail: "Not authenticated" })));

  await page.route(api("/api/auth/login"), async (route) => {
    if (route.request().method() === "OPTIONS") return fulfill(route, 204);
    const body = route.request().postDataJSON() as { username: string; password: string };
    if (options.loginAs && body.password === "correct horse battery") {
      me = options.loginAs;
      await setSessionCookies(page.context());
      return fulfill(route, 200, me);
    }
    return fulfill(route, 401, { detail: "Invalid username or password." });
  });

  await page.route(api("/api/auth/logout"), async (route) => {
    if (route.request().method() !== "OPTIONS") {
      me = null;
      await page.context().clearCookies();
    }
    return fulfill(route, 204);
  });

  await page.route(api("/api/auth/role"), async (route) => {
    if (route.request().method() === "OPTIONS") return fulfill(route, 204);
    const { role } = route.request().postDataJSON() as { role: Role };
    const next = options.roleSwitch?.[role];
    if (!next) return fulfill(route, 403, { detail: "Role not held" });
    me = next;
    return fulfill(route, 200, me);
  });

  await page.route(api("/api/auth/password"), async (route) => {
    if (route.request().method() === "OPTIONS") return fulfill(route, 204);
    const body = route.request().postDataJSON() as { current_password: string; new_password: string };
    if (body.current_password !== "correct horse battery") {
      return fulfill(route, 400, { detail: "Current password is incorrect" });
    }
    return fulfill(route, 204);
  });

  return { requests, current: () => me };
}

/** POST /api/session returning a session with no brief stream. */
export async function mockCreateSession(page: Page, sessionId = "smoke-session-1", courseUuid?: string) {
  await page.route(api("/api/session"), async (route) => {
    if (route.request().method() === "OPTIONS") return fulfill(route, 204);
    const { course_id } = route.request().postDataJSON() as { course_id: string };
    return fulfill(route, 201, {
      session_id: sessionId,
      person_id: null,
      course_uuid: courseUuid ?? course_id,
      brief_turn_id: null,
      stream_url: null,
    });
  });
}
