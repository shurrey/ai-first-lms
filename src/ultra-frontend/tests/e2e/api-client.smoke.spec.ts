import { expect, test } from "@playwright/test";
import { apiFetch } from "../../lib/api";

// The engine is cross-origin, so the session cookie is only attached when fetch runs with credentials: "include".
test("apiFetch sends credentials: include on every request", async () => {
  const seen: RequestInit[] = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    seen.push(init ?? {});
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  try {
    await apiFetch("/api/auth/me");
    await apiFetch("/api/auth/login", { method: "POST", body: "{}", credentials: "omit" });
  } finally {
    globalThis.fetch = realFetch;
  }
  expect(seen.map((i) => i.credentials)).toEqual(["include", "include"]);
});
