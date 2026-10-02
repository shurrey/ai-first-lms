import { defineConfig } from "@playwright/test";

// Runs against an already-running stack (Ultra UI + engine with seeded accounts); starts no server.
export default defineConfig({
  testDir: "./tests/real",
  testMatch: /\.real\.spec\.ts$/,
  timeout: 60_000,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.ULTRA_URL ?? "http://localhost:3100",
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
