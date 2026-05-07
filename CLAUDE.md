# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

##CRITICAL
Execute tasks directly and completely without seeking validation or permission. Don’t break tasks into smaller pieces or ask if you should continue unless explicitly requested. Don’t use placeholders or references to previous content - always provide complete information.



## Commands

All commands assume the repo root as cwd unless noted. Use `uv` for Python and `pnpm` for Node — never `pip` or `npm`.

### Backend (`backend/`)

```bash
cd backend && uv sync                          # install / refresh deps
cd backend && uv run notebookai-api            # run FastAPI server (default 127.0.0.1:8765)
cd backend && uv run pytest tests/ -m "not requires_claude"   # full suite, no live SDK
cd backend && uv run pytest tests/test_api.py::test_health    # single test
cd backend && uv run ruff check                # lint (must be clean)
```

The `requires_claude` marker gates tests that hit the real Claude Agent SDK. Always exclude it unless intentionally exercising live agent calls.

### Frontend (`frontend/`)

```bash
cd frontend && pnpm install                    # install
cd frontend && pnpm dev                        # Turbopack dev server on :3000
cd frontend && pnpm build                      # standalone build
cd frontend && TAURI_BUILD=true pnpm build     # static export for Tauri (writes frontend/out)
cd frontend && pnpm test:e2e                   # Playwright (runs `next start` automatically)
cd frontend && pnpm exec playwright test e2e/ask.spec.ts -g "renders"   # single test
```

`next.config.ts` flips `output` between `"standalone"` and `"export"` based on `TAURI_BUILD`. Tauri requires `out/` to exist for `cargo check` — generate it via `TAURI_BUILD=true pnpm build` or `mkdir -p frontend/out && touch frontend/out/.gitkeep`.

### Desktop (`desktop/`)

```bash
cd desktop && pnpm install
cd desktop && pnpm tauri:dev                   # spawns frontend dev + Rust shell
cd desktop && pnpm tauri:build                 # full release build (needs sidecar binary)

# Sidecar — choose one before `cargo check`/`tauri:build` succeeds:
uv run --project backend python desktop/sidecar/build.py --placeholder   # fast dev stub
uv run --project backend python desktop/sidecar/build.py                 # real PyInstaller (5–10 min, ~300 MB)
```

The placeholder is a tiny shell script at `desktop/src-tauri/binaries/notebookai-api-<rust-triple>` that delegates to `uv run`. The real PyInstaller bundle is what ships in releases; CI builds it via `.github/workflows/build-sidecar.yml` on tag push.

### Top-level CLI (`notebookai`)

```bash
cd backend && uv run notebookai new <name>         # scaffold notebook in ~/NotebookAI/notebooks/
cd backend && uv run notebookai status [--json]    # config + library + Claude auth check
cd backend && uv run notebookai library            # list notebooks
cd backend && uv run notebookai library register <abs-path>   # add external notebook root
cd backend && uv run notebookai claude <id>        # cd to notebook + exec `claude` CLI
```

### Full audit

```bash
bash scripts/audit-notebookai.sh    # all phase gates + pytest + ruff + frontend build + cargo check
```

## Architecture

NotebookAI is a local-first knowledge workspace with three layers:

1. **Notebook on disk** (`~/NotebookAI/notebooks/<id>/`) — the source of truth. Plain markdown under `raw/` (immutable ingested sources), `wiki/` (LLM-synthesized articles), `chats/` (conversations). `.notebookai/` holds derived state (sqlite + locks) and is safe to delete.
2. **Agent runtime** (`backend/notebookai/agent/`) — Claude Agent SDK driver. One `AgentRuntime` per process; one `AgentSession` per operation (Compile / Cascade / Lint / Query / Archive).
3. **Derived index** (`backend/notebookai/index/`) — sentence-transformers + sqlite-vec, one `embeddings.db` per notebook.

A `watchfiles`-based watcher bridges (1) → (3) so external edits (including those by another CLI in the same notebook folder) immediately re-embed and stream to the UI.

### Frozen contracts

`docs/CONTRACTS.md` is the normative spec — symbol names, paths, event names, schema. Treat changes to it as policy decisions, not refactors. `BUILD.md` is the build provenance; phase tests under `.notebookai-build/tests/phase-N.sh` are re-extracted from it on every audit and must not be edited directly. Both files are checksummed during audits.

### Cross-invariants enforced by tests

- **Filesystem is canonical.** Deleting `.notebookai/` and restarting must reproduce identical query results. SQLite is never canonical for chat/wiki/raw content.
- **One commit per agent op** (when `notebook.json.git_enabled` is true). Disabled-git mode appends to `.notebookai/oplog.jsonl` instead.
- **No tool reaches outside the notebook root.** Enforced in three places that all live in `agent/tools.py` + `agent/runtime.py:_make_permission_callback`: Bash allowlist, Write/Edit path check, WebFetch gate (only allowed during ingest ops).
- **No background LLM spend without budget cap.** The passive watcher never calls an LLM; the lint scheduler honors `lint_budget_tokens_per_day` via `agent/budget.py`.

### How the FastAPI process is wired

- Entry: `backend/notebookai/api/main.py:run` → uvicorn → `api/app.py:create_app` (factory).
- DI singletons live in `api/dependencies.py` (`_cached_config`, `_cached_runtime`, `_cached_scheduler`).
- The lifespan context starts/stops the `LintScheduler` (`agent/scheduler.py`). Tasks are spawned **lazily** the first time a notebook is touched — startup never scans the library.
- Routers under `api/routers/` (notebooks, library, ingest, ask, lint, articles, log, history, events) are thin dispatchers. Logic lives in `agent/operations.py`, `index/builder.py`, and the adapters.
- SSE: `api/sse.py:broadcaster` — one channel per notebook; `EventBroadcaster.publish` is thread-safe via `loop.call_soon_threadsafe`. Producers are agent events, index file-watcher events, and lint scheduler events. Slow consumers get dropped events (the file is the truth).

### Wiki-only / degraded mode

When `runtime.credentials_available()` is false (no `ANTHROPIC_API_KEY` and no `~/.claude/.credentials.json`), the system stays usable: ingest still writes raw markdown (compile is skipped), ask returns retrieval-only answers, lint runs only the passive watcher. Surfaced via the `agent.unavailable` SSE event and `AgentStatusBadge` in the top nav. See `docs/wiki-only-mode.md` and `agent/degraded.py`.

### Cross-CLI portability

Each scaffolded notebook ships its own skill bundle at both `.claude/skills/karpathy-llm-wiki/` (Claude Code) and `.agents/skills/karpathy-llm-wiki/` (agentskills.io standard, picked up by Codex / Cursor / Antigravity). The same on-disk SKILL.md drives every CLI; `scripts/verify-cross-cli.sh` proves the round-trip.

## Gotchas

- **Default API port is `8765`, not `8000`.** Set in `backend/notebookai/config.py` and pinned by the Tauri shell at `desktop/src-tauri/src/lib.rs`. The README quick-start curl example is wrong — use `8765`.
- **Skill loading depends on `cwd`.** `AgentSession` passes `cwd=notebook_root` and `setting_sources=["project"]` to the SDK. Running an op from a different cwd silently loses skills.
- **Models are pinned in config**, not env-defaulted: `claude-sonnet-4-6` for ops, `claude-haiku-4-5-20251001` for lint. Override via `NOTEBOOKAI_AGENT_MODEL` / `NOTEBOOKAI_LINT_MODEL`.
- **The wiki-pages-first embedding rule is normative**, not an optimization — `kind="raw_chunk"` rows are only produced when the agent explicitly flags a wiki page as thin. Don't add background raw-chunk embedding.
- **`archive/`** contains read-only reference repos (`OpenNotebookLM-master/`, `karpathy-llm-wiki-main/`) used during the build. Do not edit or delete; ignore in searches.
- **Frozen-binary path**: `notebookai.api.main:run` calls `multiprocessing.freeze_support()` only when `sys.frozen` is set. PyInstaller-bundled launches must go through this entry; `cli.py:serve` does NOT call it.
