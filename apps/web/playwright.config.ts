import { defineConfig, devices } from "@playwright/test";

// SKEL-007 smoke test. Both servers are started here on dedicated ports
// (test_dev_lifecycle.py uses OS-assigned ephemeral ports; `tasks.py dev`
// defaults to 8000/3000), and an already-running server is never reused.
// The API is e2e/api_launcher.py: a test-only launcher with SQLite storage and
// a fixed fake model, not the environment-based production wiring.
const E2E_API_PORT = 8131;
const E2E_WEB_PORT = 3131;
const E2E_API_ORIGIN = `http://127.0.0.1:${E2E_API_PORT}`;
const E2E_WEB_ORIGIN = `http://localhost:${E2E_WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  // The first request to `next dev` compiles the page.
  timeout: 120_000,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: E2E_WEB_ORIGIN,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run --locked python apps/web/e2e/api_launcher.py --port ${E2E_API_PORT}`,
      cwd: "../..",
      url: `${E2E_API_ORIGIN}/health`,
      env: { AI_QA_COPILOT_E2E: "1" },
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
    {
      command: `npm run dev -- --hostname localhost --port ${E2E_WEB_PORT}`,
      url: E2E_WEB_ORIGIN,
      env: {
        API_BASE_URL: E2E_API_ORIGIN,
        // Empty values keep Cognito sign-in disabled, so the app uses the
        // API's local bypass.
        NEXT_PUBLIC_API_BASE_URL: "",
        NEXT_PUBLIC_COGNITO_DOMAIN: "",
        NEXT_PUBLIC_COGNITO_CLIENT_ID: "",
        NEXT_PUBLIC_AUTH_REDIRECT_URI: "",
        NEXT_PUBLIC_AUTH_LOGOUT_URI: "",
      },
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
  ],
});
