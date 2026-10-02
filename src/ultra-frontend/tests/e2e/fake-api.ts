import type { Page, Route } from "@playwright/test";

/** Origin baked into NEXT_PUBLIC_API_URL for the smoke dev server; never resolvable. */
export const FAKE_API_ORIGIN = "http://api.smoke.test";

export const CS101_ID = "bdd640fb-0667-4ad1-9c80-317fa3b1799d";
export const EMMA_ID = "5be6128e-18c2-4797-a142-ea7d17be3111";

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "access-control-allow-headers": "*",
};

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

const PERSONS_BY_PERSONA: Record<string, string> = {
  student: EMMA_ID,
  faculty: "17fc695a-07a0-4a6e-8822-e8f36c031199",
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", headers: CORS_HEADERS, body: JSON.stringify(body) });
}

/**
 * Routes every request to FAKE_API_ORIGIN through canned engine responses.
 * Returns the list of requests that matched no handler, so a spec can assert it stays empty.
 */
export async function mockEngine(page: Page): Promise<string[]> {
  const unhandled: string[] = [];

  await page.route(`${FAKE_API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;

    if (req.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS_HEADERS });
    }

    // Shape of CreateSessionResponse (src/engine/api/session.py).
    if (req.method() === "POST" && path === "/api/session") {
      const body = req.postDataJSON() as { persona: string; course_id: string };
      const sessionId = `smoke-session-${body.persona}`;
      const briefTurnId = `brief-${sessionId}`;
      return json(
        route,
        {
          session_id: sessionId,
          person_id: PERSONS_BY_PERSONA[body.persona] ?? null,
          course_uuid: body.course_id,
          brief_turn_id: briefTurnId,
          stream_url: `/api/stream?session_id=${sessionId}&turn_id=${briefTurnId}`,
        },
        201,
      );
    }

    if (req.method() === "GET" && path === "/api/stream") {
      return route.fulfill({ status: 200, contentType: "text/event-stream", headers: CORS_HEADERS, body: "" });
    }

    if (req.method() === "GET" && path === `/api/mastery/${EMMA_ID}/${CS101_ID}`) {
      return json(route, EMMA_CS101_MASTERY);
    }

    // The faculty default persona renders first; an empty roster keeps that view inert.
    if (req.method() === "GET" && path.startsWith("/api/roster/")) {
      return json(route, { students: [], total: 0 });
    }

    if (req.method() === "GET" && path === `/api/student-insights/${EMMA_ID}`) {
      return json(route, { insights: ["You learn fastest from worked examples."] });
    }

    if (req.method() === "GET" && path === `/api/student-goals/${EMMA_ID}`) {
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

    unhandled.push(`${req.method()} ${path}${url.search}`);
    return json(route, { detail: "not mocked" }, 404);
  });

  return unhandled;
}
