import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60000,
  retries: 0,
  use: {
    baseURL: "http://localhost:3100",
    headless: true,
    actionTimeout: 15000,
  },
  webServer: {
    command: "pnpm dev --port 3100",
    port: 3100,
    reuseExistingServer: true,
    timeout: 60000,
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
