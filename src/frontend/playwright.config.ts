import { defineConfig } from "@playwright/test";

// 3000 and 3100 are the dockerised UIs; e2e runs its own dev server on a free port.
const PORT = Number(process.env.E2E_PORT ?? 3120);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60000,
  retries: 0,
  use: {
    baseURL: `http://localhost:${PORT}`,
    headless: true,
    actionTimeout: 15000,
  },
  webServer: {
    command: `pnpm dev --port ${PORT}`,
    port: PORT,
    reuseExistingServer: false,
    timeout: 60000,
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
