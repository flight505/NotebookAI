import { test, expect } from "@playwright/test";
import {
  buildDefaultFixtures,
  mockBackend,
  seedNotebookState,
} from "./fixtures/api-mocks";

test.describe("Ask mode", () => {
  test.beforeEach(async ({ page }) => {
    await seedNotebookState(page);
  });

  test("shows empty composer initially", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/ask");
    const composer = page.getByTestId("chat-composer-textarea");
    await expect(composer).toBeVisible();
    await expect(composer).toHaveValue("");
    // No streaming bubble yet.
    await expect(page.getByTestId("streaming-message")).toHaveCount(0);
  });

  test("sends a query and renders streaming response", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/ask");
    const composer = page.getByTestId("chat-composer-textarea");
    await composer.fill("What are transformers?");
    await page.getByTestId("chat-composer-send").click();

    // After agent.done, the streaming hook stores the chat_id from the SSE
    // sequence, the URL is updated, and the chat is refetched. The new
    // assistant message lands in the transcript with the streamed summary.
    await expect(page).toHaveURL(/chat=chat-new/, { timeout: 10_000 });
    const assistant = page
      .getByTestId("chat-message")
      .filter({ has: page.locator('[data-role="assistant"]') })
      .first();
    await expect(
      page
        .getByTestId("chat-message")
        .filter({ hasText: "Transformers are a neural network architecture." }),
    ).toBeVisible({ timeout: 10_000 });
    void assistant; // Reference suppresses unused-var lint.
  });

  test("citation chips link into Read mode", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/ask");
    await page.getByTestId("chat-composer-textarea").fill("Cite something");
    await page.getByTestId("chat-composer-send").click();

    // Wait for the right-rail citation chip to render.
    const chip = page.getByTestId("citation-chip").first();
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toHaveAttribute(
      "data-article-path",
      "wiki/ml/transformers.md",
    );
    // Citation chips are <a> tags pointing to /read?article=...
    const href = await chip.getAttribute("href");
    expect(href).toContain("/read?article=");
    expect(href).toContain("ml%2Ftransformers.md");
  });

  test("shows degraded banner in wiki-only mode", async ({ page }) => {
    const fixtures = buildDefaultFixtures({
      agentStatus: { available: false, reason: "ANTHROPIC_API_KEY missing" },
      notebooks: [
        {
          id: "nb-test",
          name: "Test Notebook",
          path: "/tmp/test-notebook",
          agent_status: {
            available: false,
            reason: "ANTHROPIC_API_KEY missing",
          },
        },
      ],
    });
    await mockBackend(page, fixtures);
    await page.goto("/ask");
    const banner = page.getByTestId("degraded-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Wiki-only mode");
  });
});
