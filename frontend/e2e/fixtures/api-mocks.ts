import type { Page, Route } from "@playwright/test";

/**
 * Reusable Playwright mocks for the FastAPI backend. Tests register a
 * `mockBackend(page, fixtures)` call before navigating; every `**\/api\/**`
 * request the frontend issues is intercepted and answered from the fixture
 * data — no real backend, no flakiness, sub-second test runs.
 */

export interface MockNotebook {
  id: string;
  name: string;
  path: string;
  agent_status?: { available: boolean; reason: string | null };
}

export interface MockArticle {
  path: string;
  title: string;
  content: string;
  frontmatter?: Record<string, unknown>;
  backlinks?: string[];
  outlinks?: string[];
  raw_refs?: string[];
  updated_at?: string;
}

export interface MockChat {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  path: string;
  notebook_id?: string;
  model?: string | null;
  messages?: Array<{
    id: string;
    role: "user" | "assistant" | "system";
    text: string;
    citations?: Array<{
      article_path: string;
      quote?: string;
      score?: number | null;
    }>;
  }>;
}

export interface MockFinding {
  id: string;
  notebook_id: string;
  kind: string;
  status: "open" | "accepted" | "rejected" | "auto_fixed" | "resolved";
  payload?: Record<string, any> | null;
}

export interface MockBudget {
  notebook_id: string;
  day: string;
  input_tokens_used: number;
  output_tokens_used: number;
  input_limit: number;
  output_limit: number;
  last_op_at: string | null;
  denied_op_count: number;
}

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface MockFixtures {
  notebooks: MockNotebook[];
  library?: Array<{
    id: string;
    name: string;
    path: string;
    created_at: string | null;
    last_op_at: string | null;
    article_count: number;
    chat_count: number;
    is_external: boolean;
    git_enabled: boolean;
  }>;
  articles: MockArticle[];
  chats: MockChat[];
  findings: MockFinding[];
  budget: MockBudget;
  agentStatus: { available: boolean; reason: string | null };
  /** Events to emit as SSE for /ask streaming. */
  askEvents?: SseEvent[];
  /** Events to emit on /events activity stream. */
  activityEvents?: SseEvent[];
  /** Captures requests so tests can assert on them. */
  recorded?: { method: string; url: string; body?: unknown }[];
}

/**
 * Build the default fixture: 1 notebook, 3 articles in wiki/, 2 chats,
 * library scan, agent_status=available, an SSE sequence covering
 * agent.tool_call → agent.message (chunked) → agent.done, two lint
 * findings, and a 25k/50k input budget.
 */
export function buildDefaultFixtures(
  overrides: Partial<MockFixtures> = {},
): MockFixtures {
  const notebookId = "nb-test";
  const articles: MockArticle[] = [
    {
      path: "ml/transformers.md",
      title: "Transformers",
      content: [
        "# Transformers",
        "",
        "Transformers are a neural network architecture introduced in 2017.",
        "",
        "See also [[attention]] and [[ml/embeddings]].",
      ].join("\n"),
      backlinks: ["ml/attention.md", "ml/embeddings.md"],
      outlinks: ["ml/attention.md", "ml/embeddings.md"],
      raw_refs: [],
      frontmatter: {},
      updated_at: "2026-04-01T00:00:00Z",
    },
    {
      path: "ml/attention.md",
      title: "Attention",
      content: [
        "# Attention",
        "",
        "Attention mechanisms power [[transformers]].",
      ].join("\n"),
      backlinks: ["ml/transformers.md"],
      outlinks: ["ml/transformers.md"],
      raw_refs: [],
      frontmatter: {},
      updated_at: "2026-04-02T00:00:00Z",
    },
    {
      path: "ml/embeddings.md",
      title: "Embeddings",
      content: [
        "# Embeddings",
        "",
        "Embeddings are dense vectors. They underpin [[transformers]].",
      ].join("\n"),
      backlinks: ["ml/transformers.md"],
      outlinks: ["ml/transformers.md"],
      raw_refs: [],
      frontmatter: {},
      updated_at: "2026-04-03T00:00:00Z",
    },
  ];

  const chats: MockChat[] = [
    {
      id: "chat-1",
      title: "What are transformers?",
      created_at: "2026-04-04T00:00:00Z",
      updated_at: "2026-04-04T00:01:00Z",
      message_count: 2,
      path: "chats/chat-1.md",
      notebook_id: notebookId,
      model: "claude-sonnet-4-5",
      messages: [
        { id: "m1", role: "user", text: "What are transformers?" },
        {
          id: "m2",
          role: "assistant",
          text: "Transformers are a neural net architecture.",
          citations: [
            { article_path: "wiki/ml/transformers.md", quote: "introduced in 2017" },
          ],
        },
      ],
    },
    {
      id: "chat-2",
      title: "Embeddings deep-dive",
      created_at: "2026-04-05T00:00:00Z",
      updated_at: "2026-04-05T00:01:00Z",
      message_count: 0,
      path: "chats/chat-2.md",
      notebook_id: notebookId,
      model: null,
      messages: [],
    },
  ];

  const findings: MockFinding[] = [
    {
      id: "f1",
      notebook_id: notebookId,
      kind: "broken_link",
      status: "open",
      payload: {
        path: "ml/transformers.md",
        message: "Missing target [[transfomer]] (typo).",
        suggested_fix: "- [[transfomer]]\n+ [[transformers]]",
        source: "passive",
      },
    },
    {
      id: "f2",
      notebook_id: notebookId,
      kind: "orphan",
      status: "open",
      payload: {
        path: "raw/old-notes.md",
        message: "Raw file is orphaned (never compiled).",
        source: "passive",
      },
    },
  ];

  const askEvents: SseEvent[] = [
    {
      event: "agent.tool_call",
      data: {
        tool: "Read",
        input: { path: "wiki/ml/transformers.md" },
        op_id: "op-1",
      },
    },
    { event: "agent.message", data: { text: "Transformers ", op_id: "op-1" } },
    { event: "agent.message", data: { text: "are a ", op_id: "op-1" } },
    { event: "agent.message", data: { text: "neural network ", op_id: "op-1" } },
    { event: "agent.message", data: { text: "architecture.", op_id: "op-1" } },
    {
      event: "agent.done",
      data: {
        chat_id: "chat-new",
        summary: "Transformers are a neural network architecture.",
        op_id: "op-1",
      },
    },
  ];

  const activityEvents: SseEvent[] = [
    {
      event: "agent.tool_call",
      data: { tool: "Read", input: { path: "wiki/ml/transformers.md" }, op_id: "op-99" },
    },
    {
      event: "agent.message",
      data: { text: "Reading the article…", op_id: "op-99" },
    },
    { event: "agent.done", data: { summary: "done", op_id: "op-99" } },
  ];

  const base: MockFixtures = {
    notebooks: [
      {
        id: notebookId,
        name: "Test Notebook",
        path: "/tmp/test-notebook",
        agent_status: { available: true, reason: null },
      },
    ],
    library: [
      {
        id: notebookId,
        name: "Test Notebook",
        path: "/tmp/test-notebook",
        created_at: "2026-04-01T00:00:00Z",
        last_op_at: "2026-04-04T00:01:00Z",
        article_count: 3,
        chat_count: 2,
        is_external: false,
        git_enabled: true,
      },
    ],
    articles,
    chats,
    findings,
    budget: {
      notebook_id: notebookId,
      day: "2026-05-07",
      input_tokens_used: 25_000,
      output_tokens_used: 2_500,
      input_limit: 50_000,
      output_limit: 10_000,
      last_op_at: null,
      denied_op_count: 0,
    },
    agentStatus: { available: true, reason: null },
    askEvents,
    activityEvents,
    recorded: [],
  };

  return { ...base, ...overrides };
}

/**
 * Encode a list of SSE events as a single response body:
 *   event: foo\ndata: {...}\n\n
 */
export function encodeSse(events: SseEvent[]): string {
  return (
    events
      .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n`)
      .join("\n") + "\n"
  );
}

/**
 * Sleep wrapper so we can chunk SSE writes if the caller wants char-by-char
 * streaming feel. Currently not used — Playwright fulfill body is delivered
 * atomically — but kept for symmetry with the production server.
 */
export async function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Register all `**\/api\/**` route handlers. Call once per test before
 * `page.goto(...)`.
 */
export async function mockBackend(
  page: Page,
  fixtures: MockFixtures = buildDefaultFixtures(),
): Promise<MockFixtures> {
  fixtures.recorded = fixtures.recorded ?? [];

  // Register the catch-all FIRST so more specific routes registered below
  // take precedence (Playwright matches routes in reverse order).
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    let body: unknown = undefined;
    try {
      body = req.postDataJSON();
    } catch {
      body = req.postData();
    }
    fixtures.recorded!.push({
      method: req.method(),
      url: req.url(),
      body,
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });

  // Helper: capture the request before fulfilling.
  const record = async (route: Route) => {
    const req = route.request();
    let body: unknown = undefined;
    try {
      body = req.postDataJSON();
    } catch {
      body = req.postData();
    }
    fixtures.recorded!.push({
      method: req.method(),
      url: req.url(),
      body,
    });
  };

  await page.route("**/api/library", async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixtures.library ?? []),
    });
  });

  await page.route("**/api/library/register", async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "nb-registered",
        name: "registered",
        path: "/tmp/registered",
        created_at: new Date().toISOString(),
        last_op_at: null,
        article_count: 0,
        chat_count: 0,
        is_external: true,
        git_enabled: false,
      }),
    });
  });

  await page.route("**/api/notebooks", async (route) => {
    await record(route);
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { name?: string };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "nb-created",
          name: body?.name ?? "new",
          path: "/tmp/nb-created",
          created_at: new Date().toISOString(),
          schema_version: 1,
          git_enabled: true,
          agent: {
            model: "claude-sonnet-4-5",
            lint_model: "claude-haiku-3-5",
            lint_schedule: "daily",
            lint_budget_tokens_per_day: 50_000,
          },
          embeddings: { model: "bge-small-en-v1.5", dim: 384 },
          stats: {
            raw_count: 0,
            wiki_count: 0,
            chat_count: 0,
            last_op_at: null,
          },
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixtures.notebooks),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+$/, async (route) => {
    await record(route);
    const id = route.request().url().split("/").pop()!;
    const nb = fixtures.notebooks.find((n) => n.id === id) ??
      fixtures.notebooks[0];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: nb.id,
        name: nb.name,
        path: nb.path,
        created_at: "2026-04-01T00:00:00Z",
        schema_version: 1,
        git_enabled: true,
        agent: {
          model: "claude-sonnet-4-5",
          lint_model: "claude-haiku-3-5",
          lint_schedule: "daily",
          lint_budget_tokens_per_day: 50_000,
        },
        embeddings: { model: "bge-small-en-v1.5", dim: 384 },
        stats: { raw_count: 0, wiki_count: 3, chat_count: 2, last_op_at: null },
        agent_status: nb.agent_status ?? fixtures.agentStatus,
      }),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/articles$/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixtures.articles),
    });
  });

  await page.route(
    /\/api\/notebooks\/[^/]+\/articles\/[^?]+\/backlinks/,
    async (route) => {
      await record(route);
      const url = route.request().url();
      const match = url.match(/articles\/([^?]+)\/backlinks/);
      const target = match ? decodeURIComponent(match[1]) : "";
      const linkers = fixtures.articles.filter((a) =>
        (a.outlinks ?? []).some(
          (o) =>
            o === target ||
            o + ".md" === target ||
            o === target.replace(/\.md$/, ""),
        ),
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          linkers.map((a) => ({
            source_path: a.path,
            source_title: a.title,
            context_snippet: a.content.slice(0, 80),
          })),
        ),
      });
    },
  );

  await page.route(/\/api\/notebooks\/[^/]+\/articles\/[^?]+$/, async (route) => {
    await record(route);
    const url = route.request().url();
    const match = url.match(/articles\/([^?]+)/);
    const path = match ? decodeURIComponent(match[1]) : "";
    const article = fixtures.articles.find((a) => a.path === path);
    if (!article) {
      await route.fulfill({ status: 404, body: "not found" });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        path: article.path,
        title: article.title,
        content: article.content,
        frontmatter: article.frontmatter ?? {},
        backlinks: article.backlinks ?? [],
        outlinks: article.outlinks ?? [],
        raw_refs: article.raw_refs ?? [],
        updated_at: article.updated_at ?? "2026-04-01T00:00:00Z",
      }),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/chats$/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        fixtures.chats.map((c) => ({
          id: c.id,
          title: c.title,
          created_at: c.created_at,
          updated_at: c.updated_at,
          message_count: c.message_count,
          path: c.path,
        })),
      ),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/chats\/[^/]+$/, async (route) => {
    await record(route);
    const id = route.request().url().split("/").pop()!;
    if (route.request().method() === "DELETE") {
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    const chat = fixtures.chats.find((c) => c.id === id);
    if (!chat) {
      // Synthesize a chat for ids returned by the streaming mock
      // (e.g. chat-new) so the post-stream refetch finds the assistant
      // message that mirrors the SSE summary.
      const summaryEvent = (fixtures.askEvents ?? []).find(
        (e) => e.event === "agent.done",
      );
      const summary =
        (summaryEvent?.data?.["summary"] as string | undefined) ?? "";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id,
          title: "New chat",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          notebook_id: "nb-test",
          model: "claude-sonnet-4-5",
          messages: [
            {
              id: "m-stream-user",
              role: "user",
              text: "(synthetic prompt)",
            },
            {
              id: "m-stream-asst",
              role: "assistant",
              text: summary,
              citations: [
                {
                  article_path: "wiki/ml/transformers.md",
                  quote: "",
                },
              ],
            },
          ],
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: chat.id,
        title: chat.title,
        created_at: chat.created_at,
        updated_at: chat.updated_at,
        notebook_id: chat.notebook_id,
        model: chat.model,
        messages: chat.messages ?? [],
      }),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/ask/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "cache-control": "no-cache", connection: "keep-alive" },
      body: encodeSse(fixtures.askEvents ?? []),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/lint\/findings$/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixtures.findings),
    });
  });

  await page.route(
    /\/api\/notebooks\/[^/]+\/lint\/findings\/[^/]+\/resolve/,
    async (route) => {
      await record(route);
      const url = route.request().url();
      const match = url.match(/findings\/([^/]+)\/resolve/);
      const id = match ? match[1] : "";
      const action = (route.request().postDataJSON() as { action?: string })
        ?.action;
      const updated = fixtures.findings.find((f) => f.id === id);
      if (updated) {
        updated.status = action === "accept" ? "accepted" : "rejected";
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updated ?? { id, status: "rejected" }),
      });
    },
  );

  await page.route(/\/api\/notebooks\/[^/]+\/lint\/budget$/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixtures.budget),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/lint$/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job_id: "lint-job-1" }),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/log/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/history/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route(/\/api\/notebooks\/[^/]+\/events/, async (route) => {
    await record(route);
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "cache-control": "no-cache" },
      body: encodeSse(fixtures.activityEvents ?? []),
    });
  });

  return fixtures;
}

/**
 * Seed Zustand-persisted state in localStorage so the page boots with a
 * notebook already selected and graphView toggled if requested.
 */
export async function seedNotebookState(
  page: Page,
  state: { notebookId?: string | null; showGraphView?: boolean; theme?: string } = {},
): Promise<void> {
  const value = {
    state: {
      currentNotebookId: state.notebookId ?? "nb-test",
      theme: state.theme ?? "light",
      showGraphView: state.showGraphView ?? false,
    },
    version: 0,
  };
  await page.addInitScript(
    ({ key, val }) => {
      localStorage.setItem(key, val);
    },
    { key: "notebookai-state", val: JSON.stringify(value) },
  );
}
