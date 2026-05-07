import { defineConfig, devices } from "@playwright/test";

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: isCI ? 2 : undefined,
  reporter: isCI ? [["html", { open: "never" }], ["list"]] : "list",
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    // We test against the production build (`next start`) rather than
    // `next dev` for two reasons:
    //   1. `next dev --turbopack` rejects this repo's
    //      `experimental.typedRoutes` config and exits early.
    //   2. `next dev` (webpack) crashes during SSR because the Zustand
    //      `persist` middleware touches `localStorage` outside the browser.
    // The production build is what users actually run, so testing it is
    // closer to the real thing anyway. `pnpm build` runs once via the
    // start-server pipeline; subsequent local runs reuse the existing
    // server when the port is busy.
    command: "pnpm build && pnpm exec next start --port 3000",
    port: 3000,
    reuseExistingServer: !isCI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
