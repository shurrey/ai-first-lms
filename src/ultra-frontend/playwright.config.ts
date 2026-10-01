import { defineConfig } from "@playwright/test";
import { FAKE_API_ORIGIN } from "./tests/e2e/fake-api";

// 3100 is the dockerised Ultra UI; tests run their own dev server beside it.
const PORT = Number(process.env.SMOKE_PORT ?? 3110);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    headless: true,
    actionTimeout: 15_000,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `pnpm exec next dev -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { NEXT_PUBLIC_API_URL: FAKE_API_ORIGIN },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
