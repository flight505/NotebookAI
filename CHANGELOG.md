# Changelog

All notable changes to NotebookAI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- macOS codesigning + notarization for the bundled sidecar
- Hugging Face model pre-baking into the sidecar bundle
- Wider Tauri test coverage beyond `cargo check`

## [0.3.0] — 2026-05-09

Hardening pass driven by a structural review of launch flow, runtime internals, dependency pinning, observability, and packaging. Five PRs (#8–#12), each independently revertable, merged in order on green CI.

### Added
- **`/api/internal/state` introspection endpoint** — JSON snapshot of the long-lived process: agent runtime model + credential status, scheduler per-notebook intervals + last result, broadcaster subscriber counts. Local-only; no auth surface added.
- **SSE `Last-Event-ID` replay + `stream.gap` event** — every published event is assigned a stable ULID at publish time and stored in a per-notebook ring buffer (capped at 128). Reconnecting clients (EventSource sets the header automatically) recover dropped events transparently. On `QueueFull` for a slow consumer, the broadcaster drops one envelope and inserts a synthetic `stream.gap` so the client knows to refetch.
- **Auto-rebuild on embedder swap** — `Notebook.embedding_model` + `embedding_dim` columns track what the index was built with. `IndexBuilder.bootstrap` reconciles vs the live embedder and triggers a clean rebuild on dim mismatch. `bge-small-en-v1.5` (default), `Snowflake/snowflake-arctic-embed-s`, and `BAAI/bge-m3` documented as one-env-var swaps.
- **Generated TypeScript API client** — new `pnpm gen:api` script imports the FastAPI app directly, pipes its OpenAPI schema through `openapi-typescript`, and writes `frontend/lib/api.gen.ts`. New `apiClient` (typed `openapi-fetch` instance) exposed alongside the legacy hand-written wrappers.
- **Tauri release workflow** — new `.github/workflows/release.yml` builds the PyInstaller sidecar and runs `tauri-action` per platform (macOS arm64/x64, Linux x64, Windows x64), producing `.dmg` / `.msi` / `.AppImage` / `.deb` bundles attached to a draft release on tag push.
- **`tauri-plugin-single-instance`** — second `notebookai` invocation focuses the existing window instead of double-spawning the FastAPI backend.
- **Devtools behind a Cargo feature** — `tauri-plugin-devtools` enabled by `pnpm tauri:dev` (via `--features devtools`); release builds stay lean.

### Changed
- **Lifespan owns runtime / scheduler / broadcaster** on `app.state` and drains them on shutdown (stop scheduler → close SSE subscribers → dispose `lru_cache`s) so a follow-up boot in the same process never reuses a stale instance.
- **Lint scheduler ±10% jitter** — every interval-tick sleep is randomised so N notebooks don't pile into `BudgetTracker` / Haiku at the same moment.
- **TTY-aware logging** — structlog renders `ConsoleRenderer(colors=True)` when stdout is a TTY; JSON stays for piped/captured stdout (Tauri sidecar, container logs).
- **`multiprocessing.set_start_method("spawn")`** at `api/main.py` import time — prevents the fork+CUDA/tokenizers deadlock on Linux.
- **Sidecar absolute paths** — `desktop/src-tauri/src/lib.rs` bakes the backend project dir via `env!("CARGO_MANIFEST_DIR")`; placeholder shell script resolves via `cd + pwd`. The `uv run` fallback now works regardless of the parent's cwd (cwd=/ in a packaged `.app`).
- **`AgentSession.run` asserts skill-bundle presence** — yields `AgentError(error_type="skill_missing")` before any SDK call when the karpathy-llm-wiki bundle isn't on disk; previously the SDK proceeded without the skill prompt and silently degraded.
- **WAL + perf PRAGMAs on every IndexStore connection** — `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, and a 256 MB `mmap_size`. ~3-5× cold-rebuild throughput.
- **Tauri health probe via `ureq`** — replaces the hand-rolled `TcpStream` + raw HTTP/1.0 probe (which read a single byte at offset 9 to infer status).
- **Next.js 15.4 → 15.5.18** with `experimental.reactCompiler: true` (1.0.0 stable). Auto-memoization replaces most `useMemo`/`useCallback` boilerplate.
- **Frontend CI on `ubuntu-latest`** (was `macos-14`) — Next builds are platform-agnostic; ~10× cheaper minutes.
- **Cargo cache via `Swatinem/rust-cache@v2`** — better invalidation than the hand-rolled `actions/cache@v4` keyed on `Cargo.toml`.
- **Dropped unused `output: "standalone"` Next config branch** — there was no consumer of `.next/standalone`. Tauri's `output: "export"` path unchanged.
- **Centralized Claude credential probe** in `notebookai/agent/credentials.py` (also picks up `XDG_CONFIG_HOME` for Linux); `AgentRuntime.credentials_available` and `notebookai status` both delegate.

### Fixed
- **README quick start** pointed at `localhost:8000`; default API port is `8765`. Curl example and `notebookai serve` invocation corrected.
- **`notebookai serve` ran with stdlib + structlog silenced** — `cli.py`'s import-time `setLevel(ERROR)` was never re-raised. `serve` now routes through the same `_configure_logging` path the `notebookai-api` console-script uses.

### Pinned
- `claude-agent-sdk>=0.1.76,<0.2` — the SDK is pre-1.0 and ships breaking changes within minors. Bump deliberately after re-running `tests/test_agent.py`.

### Stats
- 5 PRs merged (#8–#12)
- 143 backend tests passing (was 134), 21 Playwright e2e tests
- 9 new tests added covering the new endpoints, jitter, skill assertion, SSE replay/gap, WAL/embedder rebuild

### Migration from v0.2.0
No breaking changes. New surface is additive: `GET /api/internal/state`, `Last-Event-ID` accepted on the events stream (header or query param), `stream.gap` SSE event added to the known-events list. `Notebook.embedding_model` + `embedding_dim` columns are nullable and populate on first `IndexBuilder.bootstrap` after upgrade. Switching `NOTEBOOKAI_EMB_MODEL` triggers an automatic index rebuild — no manual step required.

## [0.2.0] — 2026-05-07

Six features that take NotebookAI from "build complete" to "feels like a product." All shipped through isolated subagents under strict input/output contracts (per BUILD.md discipline) and merged via squash-PR with green CI.

### Added
- **First-run welcome flow with demo notebook option** — new `/welcome` route guides fresh users through a 3-step onboarding (pitch → choose setup → verify Claude availability) with a hand-seeded demo notebook (3 wiki articles + 1 chat) reachable via `POST /api/library/demo`.
- **GitHub Actions CI** — pytest + ruff + pnpm build + cargo check on every PR; Playwright e2e job after the frontend job; sidecar binary build matrix on tag push.
- **Scheduled lint cron** — per-notebook hourly Haiku lint with idle detection and token-budget gating; UI shows next-run countdown.
- **Agent-unavailable graceful degradation** — when Claude credentials are missing, NotebookAI now runs in "wiki-only mode": ingest still saves raw markdown (compile skipped), ask returns retrieval-only answers from the local index, and lint runs the passive watcher only. Surfaced via a top-nav badge, a banner on the ask page, and a new `agent.unavailable` SSE event. See [docs/wiki-only-mode.md](docs/wiki-only-mode.md).
- **Playwright e2e suite** — 16 browser tests (21 with welcome) across Read, Ask, Curate, Library, Welcome modes; ~20s wall-time; deterministic via per-test API mocking (no real backend); 13 components got `data-testid` attributes for selector stability. New `pnpm test:e2e` script; CI runs the suite in a dedicated `e2e` job.
- **Real app icons + brand mark** — bold cream "N" on an ink-blue squircle with a single amber "AI node" accent. Generated from a single Python script ([`desktop/sidecar/generate_icons.py`](desktop/sidecar/generate_icons.py)) that emits every Tauri size, ICNS, ICO, and the web favicon. See [`docs/branding.md`](docs/branding.md).
- **PyInstaller-bundled sidecar** — the Tauri desktop app now ships a single-file backend binary (`desktop/sidecar/build.py` produces `notebookai-api-<rust-target-triple>`), so end-users no longer need `uv` installed. Tauri picks up the binary via `bundle.externalBin`; the Rust shell falls back to `uv run` for the developer loop when no bundled binary is present. CI matrix in `.github/workflows/build-sidecar.yml` builds for macOS arm64/x64, Linux x64/arm64, and Windows x64.

### Stats
- 7 PRs merged (#1–#6 plus the initial CI commit)
- 134 backend tests passing (was 114), 21 Playwright e2e tests
- ~25,000 source LOC (was ~14,400)

### Migration from v0.1.0
No breaking changes. New endpoints are additive (`POST /api/library/demo`, `GET/POST /api/notebooks/{id}/lint/schedule`, `POST .../lint/run-now`). `GET /api/notebooks/{id}` response gained `agent_status: {available, reason}`. New SSE events: `agent.unavailable`, `lint.scheduled`, `lint.skipped`, `lint.run_complete`. `notebook.json` schema additions are optional (`lint_schedule_enabled`, `lint_schedule_interval_minutes`); existing notebooks keep working with defaults.

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
