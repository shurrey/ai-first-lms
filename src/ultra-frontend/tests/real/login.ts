import { expect, test, type Page } from "@playwright/test";

export const ENGINE_URL = process.env.ENGINE_URL ?? "http://localhost:8000";

/** Skips the calling test when the seed password is not in the environment. */
export function requireSeedPassword(): string {
  const password = process.env.SEED_DEMO_PASSWORD;
  test.skip(!password, "SEED_DEMO_PASSWORD is not set");
  return password as string;
}

/**
 * Signs in against the real engine. page.request shares the browser context's
 * cookie jar, so the host-scoped lms_session/lms_csrf cookies apply to the UI too.
 */
export async function login(page: Page, username: string): Promise<{ person: { display_name: string }; active_role: string }> {
  const password = requireSeedPassword();
  const res = await page.request.post(`${ENGINE_URL}/api/auth/login`, { data: { username, password } });
  expect(res.status(), `login as ${username}`).toBe(200);
  return res.json();
}
