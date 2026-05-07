# NotebookAI Frontend — End-to-end Tests

Playwright suite covering the three modes: **Read**, **Ask**, **Curate** —
plus the notebook switcher / library flow. The suite runs against a Next.js
dev server with the FastAPI backend **mocked via Playwright route handlers**.
No real Python process required, no real network, deterministic in CI.

## Run locally

```bash
cd frontend
pnpm install
pnpm test:e2e:install      # one-time: installs chromium + system deps
pnpm test:e2e              # headless run
pnpm test:e2e:ui           # interactive Playwright UI
```

The Playwright config (`playwright.config.ts`) auto-spawns `pnpm dev` on
port 3000 and reuses the running server when present.

## Mocking strategy

Tests never hit the real backend. `e2e/fixtures/api-mocks.ts` exposes:

- `buildDefaultFixtures(overrides?)` — returns a sensible default scenario:
  one notebook, three articles in `wiki/`, two chats, two lint findings,
  a 50%-used budget, and an SSE event sequence
  `agent.tool_call → agent.message (×N) → agent.done`.
- `mockBackend(page, fixtures?)` — registers `page.route('**/api/**', ...)`
  handlers that fulfill every backend endpoint the frontend uses. Returns
  the fixtures object back so tests can assert on `fixtures.recorded`
  (every captured request) or mutate `fixtures.findings` between calls.
- `seedNotebookState(page)` — pre-seeds Zustand-persisted state in
  localStorage so the page boots with a notebook already selected.

SSE endpoints (`/ask`, `/events`) return a single response body that
encodes the event sequence — the frontend's reader splits on `\n\n`, so
the streaming hooks observe each chunk independently and the streaming UI
exercises the same code paths it would in production.

## Selector pattern

We use **`data-testid`** attributes exclusively — no fragile text matchers,
no class hierarchy traversal. Components carry stable, semantic testids
(`article-tree`, `chat-composer-textarea`, `finding-card`, ...). Adding a
testid is the right move when you need to target a new element in a test.

## Updating fixtures

The fixture builder is the single source of truth for default test data.
To tweak a scenario:

1. Pass `overrides` to `buildDefaultFixtures(...)` for one-off changes
   (preferred — keeps the default useful for other tests).
2. For sweeping changes (e.g. a new endpoint shape), edit the builder
   itself in `e2e/fixtures/api-mocks.ts`.

Default fixture content lives entirely in TypeScript — no JSON files —
so type-check failures show up immediately when contracts drift.

## When to add a new spec

- New mode or top-level route → new spec file (`<mode>.spec.ts`).
- New user flow within an existing mode → add a `test()` to the existing
  spec. Keep specs small and topical; one `describe` per mode.
- Bug regression → write a failing test first, then fix.

## CI

GitHub Actions runs the suite in `.github/workflows/ci.yml` under the
`e2e` job after `frontend` builds successfully. On failure the HTML
report is uploaded as a workflow artifact.

## Known issue: ArticleReader render

`lib/remarkWikilinks.ts` returns its transformer directly instead of a
unified plugin factory. When unified freezes the processor it calls the
transformer with `tree=undefined` and `unist-util-visit` throws
`Cannot use 'in' operator to search for 'children' in undefined`. The
crash happens for every article render, regardless of content.

The Read tests are written to verify what does work (article tree,
navigation URL contract, graph view, backlinks panel header) without
triggering an ArticleReader render. Once the plugin is corrected to
return a factory (`function plugin() { return function transform(tree)
{ ... }; }`), additional assertions on rendered article body content can
be added without changing the test scaffolding.
