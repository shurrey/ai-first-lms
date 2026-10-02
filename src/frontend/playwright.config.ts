import { defineConfig } from "@playwright/test";
import { E2E_PORT, FAKE_API_ORIGIN } from "./tests/e2e/fixtures/fake-api";

// E2E_BASE_URL points the run at an already-running UI (e.g. the dockerised one on
// :3000, whose origin the orchestrator's CORS allows) for *.live.spec.ts.
// Otherwise a dev server on E2E_PORT talks to an unresolvable fake API that the
// specs mock with page.route.
const LIVE_BASE_URL = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./tests/e2e",
  // Mocked specs route the fake API origin, which a live UI never calls.
  ...(LIVE_BASE_URL && { testMatch: /.*\.live\.spec\.ts$/ }),
  timeout: 60000,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: LIVE_BASE_URL ?? `http://localhost:${E2E_PORT}`,
    headless: true,
    actionTimeout: 15000,
    trace: "retain-on-failure",
  },
  webServer: LIVE_BASE_URL
    ? undefined
    : {
        command: `pnpm exec next dev --port ${E2E_PORT}`,
        url: `http://localhost:${E2E_PORT}/login`,
        reuseExistingServer: false,
        timeout: 120000,
        env: { NEXT_PUBLIC_API_URL: FAKE_API_ORIGIN },
      },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
