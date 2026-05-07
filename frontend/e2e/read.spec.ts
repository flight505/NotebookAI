import { test, expect } from "@playwright/test";
import {
  buildDefaultFixtures,
  mockBackend,
  seedNotebookState,
} from "./fixtures/api-mocks";

test.describe("Read mode", () => {
  test.beforeEach(async ({ page }) => {
    await seedNotebookState(page);
  });

  test("opens Read mode and shows article tree", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/read");
    const tree = page.getByTestId("article-tree");
    await expect(tree).toBeVisible();
    await expect(page.getByTestId("article-tree-item")).toHaveCount(3);
  });

  test("selects an article and renders markdown", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/read");
    await expect(page.getByTestId("article-tree")).toBeVisible();
    await page
      .getByTestId("article-tree-button-ml/transformers.md")
      .click();
    await expect(page).toHaveURL(/article=ml.*transformers\.md/);

    const reader = page.getByTestId("article-reader");
    await expect(reader).toHaveAttribute("data-article-path", "ml/transformers.md");
    await expect(page.getByTestId("article-title")).toHaveText("Transformers");
    await expect(page.getByTestId("article-body")).toContainText(
      "Transformers are a neural network architecture introduced in 2017.",
    );
  });

  test("wikilinks navigate within the wiki", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/read?article=ml%2Ftransformers.md");
    await expect(page.getByTestId("article-body")).toBeVisible();

    // The body links to [[attention]] and [[ml/embeddings]]; both resolve
    // to existing articles. Existing wikilinks render with class "wikilink"
    // and href=/read?article=<path>, and clicking them calls onNavigate.
    const attentionLink = page
      .getByTestId("article-body")
      .locator("a.wikilink", { hasText: "attention" });
    await expect(attentionLink).toBeVisible();
    await attentionLink.click();
    await expect(page).toHaveURL(/article=ml.*attention\.md/);
    await expect(page.getByTestId("article-title")).toHaveText("Attention");
  });

  test("shows backlinks panel header", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/read");
    await expect(page.getByText("Backlinks").first()).toBeVisible();
  });

  test("graph view toggles", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/read");
    await expect(page.getByTestId("article-tree")).toBeVisible();
    // Default state shows the Backlinks panel; the toggle button reads
    // "Graph" because clicking it switches TO graph view.
    await page.getByRole("button", { name: /Graph/ }).click();
    await expect(page.getByTestId("graph-view")).toBeVisible();
    // Three articles → three nodes in the SVG.
    const circles = page.locator('[data-testid="graph-view"] circle');
    await expect(circles).toHaveCount(3);
  });

  test("fixture builder accepts overrides", async () => {
    const fx = buildDefaultFixtures({ articles: [] });
    expect(fx.articles).toHaveLength(0);
  });
});
