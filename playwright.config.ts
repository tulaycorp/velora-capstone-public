import { defineConfig, devices } from "@playwright/test";

const appPort = Number(process.env.VELORA_E2E_APP_PORT ?? 3100);
const backendPort = Number(process.env.VELORA_E2E_BACKEND_PORT ?? 4011);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  use: {
    baseURL: `http://localhost:${appPort}`,
    trace: "retain-on-failure"
  },
  projects: [
    {
      name: "chrome",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome"
      }
    }
  ],
  webServer: [
    {
      command: "node e2e/mock-backend.mjs",
      port: backendPort,
      reuseExistingServer: !process.env.CI
    },
    {
      command: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY= CLERK_SECRET_KEY= VELORA_API_BASE_URL=http://127.0.0.1:${backendPort} VELORA_NEXT_DIST_DIR=.next-e2e npm run dev -- --port ${appPort}`,
      port: appPort,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000
    }
  ]
});
