import { test, expect } from "@playwright/test";
import { buildDefaultFixtures, mockBackend } from "./fixtures/api-mocks";

const DISMISS_KEY = "notebookai.welcome.dismissed";

async function clearDismissFlag(page: import("@playwright/test").Page) {
  await page.addInitScript((key) => {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  }, DISMISS_KEY);
}

async function setDismissFlag(page: import("@playwright/test").Page) {
  await page.addInitScript((key) => {
    try {
      window.localStorage.setItem(key, "true");
    } catch {
      /* ignore */
    }
  }, DISMISS_KEY);
}

test.describe("Welcome flow", () => {
  test("welcome shown when library empty and not dismissed", async ({ page }) => {
    await clearDismissFlag(page);
    await mockBackend(page, buildDefaultFixtures({ library: [] }));
    await page.goto("/welcome");
    await expect(page.getByTestId("welcome-shell")).toBeVisible();
    await expect(page.getByTestId("welcome-step-1")).toBeVisible();
  });

  test("welcome skipped when library has notebooks", async ({ page }) => {
    await clearDismissFlag(page);
    await mockBackend(page);
    await page.goto("/welcome");
    // Library is non-empty → page redirects to /read.
    await expect(page).toHaveURL(/\/read/);
  });

  test("welcome skipped when localStorage flag set", async ({ page }) => {
    await setDismissFlag(page);
    await mockBackend(page, buildDefaultFixtures({ library: [] }));
    await page.goto("/welcome");
    // Even with an empty library, the dismiss flag forces a /read redirect.
    await expect(page).toHaveURL(/\/read/);
  });

  test("demo notebook button creates and routes to Read mode", async ({ page }) => {
    await clearDismissFlag(page);
    const fixtures = await mockBackend(page, buildDefaultFixtures({ library: [] }));

    // Add a route override for /api/library/demo (the catch-all in
    // mockBackend would otherwise return `{}`).
    await page.route("**/api/library/demo", async (route) => {
      fixtures.recorded!.push({
        method: route.request().method(),
        url: route.request().url(),
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          notebook: {
            id: "demo-notebook",
            name: "Demo Notebook",
            path: "/tmp/demo-notebook",
            created_at: new Date().toISOString(),
            last_op_at: null,
            article_count: 3,
            chat_count: 1,
            is_external: false,
            git_enabled: true,
          },
        }),
      });
    });

    // The demo flow refetches /api/notebooks/demo-notebook on step 3,
    // which the catch-all default in mockBackend won't handle (it
    // returns `{}` without an `agent` field). Override that too.
    await page.route(/\/api\/notebooks\/demo-notebook$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "demo-notebook",
          name: "Demo Notebook",
          path: "/tmp/demo-notebook",
          created_at: new Date().toISOString(),
          schema_version: 1,
          git_enabled: true,
          agent: {
            model: "claude-sonnet-4-6",
            lint_model: "claude-haiku-4-5-20251001",
            lint_schedule: "hourly",
            lint_budget_tokens_per_day: 50_000,
          },
          embeddings: { model: "bge-small-en-v1.5", dim: 384 },
          stats: {
            raw_count: 0,
            wiki_count: 3,
            chat_count: 1,
            last_op_at: null,
          },
          agent_status: { available: true, reason: null },
        }),
      });
    });

    await page.goto("/welcome");
    await expect(page.getByTestId("welcome-step-1")).toBeVisible();
    await page.getByTestId("welcome-step-1-next").click();
    await expect(page.getByTestId("welcome-step-2")).toBeVisible();
    await page.getByTestId("welcome-create-demo").click();

    // Step 3 appears after the demo POST resolves.
    await expect(page.getByTestId("welcome-step-3")).toBeVisible();
    await expect(page.getByTestId("welcome-status-available")).toBeVisible();

    await page.getByTestId("welcome-finish").click();
    await expect(page).toHaveURL(/\/read\?notebook=demo-notebook/);

    // /api/library/demo was called.
    expect(
      fixtures.recorded!.some(
        (r) => r.method === "POST" && r.url.endsWith("/api/library/demo")
      )
    ).toBe(true);
  });

  test("agent_status shows wiki-only banner when degraded", async ({ page }) => {
    await clearDismissFlag(page);
    const fixtures = await mockBackend(page, buildDefaultFixtures({ library: [] }));

    await page.route("**/api/library/demo", async (route) => {
      fixtures.recorded!.push({
        method: route.request().method(),
        url: route.request().url(),
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          notebook: {
            id: "demo-notebook",
            name: "Demo Notebook",
            path: "/tmp/demo-notebook",
            created_at: new Date().toISOString(),
            last_op_at: null,
            article_count: 3,
            chat_count: 1,
            is_external: false,
            git_enabled: true,
          },
        }),
      });
    });

    // Force agent_status.available = false so the wiki-only banner shows.
    await page.route(/\/api\/notebooks\/demo-notebook$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "demo-notebook",
          name: "Demo Notebook",
          path: "/tmp/demo-notebook",
          created_at: new Date().toISOString(),
          schema_version: 1,
          git_enabled: true,
          agent: {
            model: "claude-sonnet-4-6",
            lint_model: "claude-haiku-4-5-20251001",
            lint_schedule: "hourly",
            lint_budget_tokens_per_day: 50_000,
          },
          embeddings: { model: "bge-small-en-v1.5", dim: 384 },
          stats: {
            raw_count: 0,
            wiki_count: 3,
            chat_count: 1,
            last_op_at: null,
          },
          agent_status: {
            available: false,
            reason: "Claude credentials not found.",
          },
        }),
      });
    });

    await page.goto("/welcome");
    await page.getByTestId("welcome-step-1-next").click();
    await page.getByTestId("welcome-create-demo").click();
    await expect(page.getByTestId("welcome-step-3")).toBeVisible();
    await expect(page.getByTestId("welcome-status-unavailable")).toBeVisible();
    await expect(page.getByTestId("welcome-status-unavailable")).toContainText(
      /Wiki-only mode/i
    );
  });
});
