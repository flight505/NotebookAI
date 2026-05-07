import { test, expect } from "@playwright/test";
import { mockBackend, seedNotebookState } from "./fixtures/api-mocks";

test.describe("Curate mode", () => {
  test.beforeEach(async ({ page }) => {
    await seedNotebookState(page);
  });

  test("activity stream renders SSE events", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/curate");
    const stream = page.getByTestId("activity-stream");
    await expect(stream).toBeVisible();
    // The fixture emits 3 events (tool_call, message, done). Single events
    // render as activity-row; events sharing op_id may collapse — wait for
    // at least one row to appear.
    await expect(
      page.getByTestId("activity-row").first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("lint findings list renders and accept works", async ({ page }) => {
    const fixtures = await mockBackend(page);
    await page.goto("/curate");
    // Two open findings in the fixture.
    await expect(page.getByTestId("finding-card")).toHaveCount(2);
    const first = page.getByTestId("finding-card").first();
    await first.getByTestId("finding-accept").click();

    // Wait for the resolve API call to be recorded.
    await expect.poll(() =>
      fixtures.recorded!.find(
        (r) =>
          r.method === "POST" &&
          r.url.includes("/lint/findings/") &&
          r.url.includes("/resolve"),
      ),
    ).toBeTruthy();

    const resolveCall = fixtures.recorded!.find(
      (r) =>
        r.method === "POST" &&
        r.url.includes("/lint/findings/") &&
        r.url.includes("/resolve"),
    );
    expect((resolveCall!.body as { action: string })?.action).toBe("accept");

    // Card collapses out — the exit animation removes it from the DOM.
    await expect(page.getByTestId("finding-card")).toHaveCount(1, {
      timeout: 5_000,
    });
  });

  test("budget meter shows token usage at ~50%", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/curate");
    const meter = page.getByTestId("budget-meter");
    await expect(meter).toBeVisible();
    // 25,000 / 50,000 = 50%.
    const inputBar = page.getByTestId("budget-bar-input");
    await expect(inputBar).toBeVisible();
    await expect(inputBar).toHaveAttribute("data-pct", "50");
  });
});
