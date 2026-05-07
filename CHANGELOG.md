# Changelog

All notable changes to NotebookAI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v0.2 milestone

### Added
- **First-run welcome flow with demo notebook option.** New `/welcome` route guides fresh users through a 3-step onboarding (pitch → choose setup → verify Claude availability) with a hand-seeded demo notebook (3 wiki articles + 1 chat) reachable via `POST /api/library/demo`.
- **GitHub Actions CI** — pytest + ruff + pnpm build + cargo check on every PR; Playwright e2e job after the frontend job; sidecar binary build matrix on tag push.
- **Scheduled lint cron** — per-notebook hourly Haiku lint with idle detection and token-budget gating; UI shows next-run countdown.
- **Agent-unavailable graceful degradation** — when Claude credentials are missing, NotebookAI now runs in "wiki-only mode": ingest still saves raw markdown (compile skipped), ask returns retrieval-only answers from the local index, and lint runs the passive watcher only. Surfaced via a top-nav badge, a banner on the ask page, and a new `agent.unavailable` SSE event. See [docs/wiki-only-mode.md](docs/wiki-only-mode.md).
- **Playwright e2e suite** — 16 browser tests across Read, Ask, Curate, Library modes; ~19s wall-time; deterministic via per-test API mocking (no real backend); 13 components got `data-testid` attributes for selector stability. New `pnpm test:e2e` script; CI runs the suite in a dedicated `e2e` job.
- **Real app icons + brand mark** — bold cream "N" on an ink-blue squircle with a single amber "AI node" accent. Generated from a single Python script ([`desktop/sidecar/generate_icons.py`](desktop/sidecar/generate_icons.py)) that emits every Tauri size, ICNS, ICO, and the web favicon. See [`docs/branding.md`](docs/branding.md).

### Planned
- PyInstaller-bundled sidecar — Tauri desktop ships without requiring `uv` on the user's machine

## [0.1.0] — 2026-05-06

Initial release. 15-phase orchestrated build of a local-first, agent-native knowledge workspace.

### Added
- **Notebook scaffold** — `notebookai new <name>` creates a folder with `raw/`, `wiki/`, `chats/`, `.notebookai/`, plus skill bundles at `.claude/skills/karpathy-llm-wiki/` and `.agents/skills/karpathy-llm-wiki/`. AGENTS.md and README.md auto-generated.
- **Derived index** — sqlite-vec + sentence-transformers (`bge-small-en-v1.5`); file watcher rebuilds embeddings on `wiki/**/*.md` changes (wiki-pages-first strategy per CONTRACTS).
- **Source adapters** — PDF (PyMuPDF + pdfminer fallback), URL (httpx + readability-lxml + html2text), YouTube (youtube-transcript-api). Topic auto-picker from existing `raw/` subdirs.
- **Wiki agent** — Claude Agent SDK runtime per notebook, loads karpathy-llm-wiki skill, permission-gated tools (Bash allowlist excludes push/pull/fetch; path-writability blocks `.git/`/`.notebookai/`/`raw/`; WebFetch gated to ingest ops).
- **REST API** — FastAPI with 9 routers (notebooks, library, ingest, ask, lint, articles, log, history, events). SSE event broadcaster with auto-reconnect.
- **Frontend** — Next.js 15 + React 19 + Tailwind 4 + Zustand. Three modes: Read (article tree, markdown reader with wikilinks/backlinks/graph view), Ask (streaming chat with citation chips, conversations as markdown), Curate (live agent activity feed, lint findings queue, token-budget meter, git history timeline).
- **Per-op git auto-commit** — every agent op produces one commit with `[op] summary` template; disabled-git mode appends to `.notebookai/oplog.jsonl`.
- **Scheduled lint** — Haiku-driven with daily token budget cap; passive watcher detects orphan-raw / broken-wikilink / broken-path-link findings without LLM spend.
- **Tauri 2 desktop shell** — native macOS vibrancy, transparent titlebar, sidecar FastAPI process.
- **Multi-notebook library** — scans `~/NotebookAI/notebooks/` plus user-registered external roots.
- **Cross-CLI verification script** (`scripts/verify-cross-cli.sh`) — proves notebooks are agent-portable across Claude Code, Codex, Cursor, Antigravity.
- **Unified CLI** — `notebookai new | serve | status | claude | codex | library | version`.
- **Centralized config** (`backend/notebookai/config.py`) reads 10 env vars; `.env.example` documents each.

### Stats
- 21 commits across 15 build phases plus 4 fix commits and the post-build hardening pass
- ~14,400 source LOC (Python, TypeScript, Rust, shell)
- 114 backend tests passing; clean ruff; `pnpm build` green; `cargo check` green
- CONTRACTS.md (611 lines) frozen as binding spec at Phase 1

### Architecture
See [VISION.md](VISION.md) for product thesis, [docs/CONTRACTS.md](docs/CONTRACTS.md) for symbol-level contracts, [docs/architecture.md](docs/architecture.md) for the stack diagram and data flow, and [BUILD.md](BUILD.md) for full build provenance.
