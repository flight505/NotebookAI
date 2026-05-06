# NotebookAI — Architecture

This document describes how the NotebookAI runtime is wired together: the layers, the data flow, the module boundaries, the design decisions, and the performance envelope. It is the engineering companion to [VISION.md](../VISION.md) (product thesis) and [CONTRACTS.md](CONTRACTS.md) (symbol-level interfaces).

## Stack diagram

```
                 ┌────────────────────────────────────────────────────────┐
                 │                  Tauri 2 desktop shell                 │
                 │   (Rust webview, ~10 MB bundle, dmg/msi/AppImage)      │
                 └───────────────────────────┬────────────────────────────┘
                                             │ loads static export
                 ┌───────────────────────────▼────────────────────────────┐
                 │     Next.js 15 + React 19 + Tailwind 4 + Zustand       │
                 │  Read mode | Ask mode | Curate mode | History | Lib    │
                 └───────────────┬─────────────────────────────┬──────────┘
                       fetch(/api)│                         SSE│ event stream
                                  │                            │
                 ┌────────────────▼────────────────────────────▼──────────┐
                 │              FastAPI surface (uvicorn)                 │
                 │   routers: notebooks, ingest, ask, wiki, curate, git   │
                 │   sse.py: typed event broker (agent.tool_call, …)      │
                 └────────┬─────────────────────────┬──────────┬──────────┘
                          │                         │          │
                ┌─────────▼─────────┐   ┌───────────▼──┐   ┌───▼────────┐
                │  Claude Agent SDK │   │ IndexBuilder │   │ git auto-  │
                │  runtime (Compile │   │ embeddings + │   │ commit     │
                │  Cascade Lint     │   │ sqlite-vec   │   │ (per op)   │
                │  Query Archive)   │   │ store        │   │            │
                └─────────┬─────────┘   └───────▲──────┘   └────────────┘
                          │                     │
                ┌─────────▼─────────────────────┴────────────────────────┐
                │            watchfiles file watcher                     │
                └────────────────────────────┬───────────────────────────┘
                                             │ inotify / FSEvents
                 ┌───────────────────────────▼────────────────────────────┐
                 │         Notebook on disk (the source of truth)         │
                 │  ~/NotebookAI/notebooks/<nb>/                          │
                 │    .notebookai/   index.db, embeddings.db, locks       │
                 │    .claude/skills/karpathy-llm-wiki/    Claude Code    │
                 │    .agents/skills/karpathy-llm-wiki/    agentskills    │
                 │    AGENTS.md  README.md                                │
                 │    raw/<topic>/YYYY-MM-DD-slug.md                      │
                 │    wiki/<topic>/<article>.md   wiki/index.md  log.md   │
                 │    chats/YYYY-MM-DD-<slug>.md                          │
                 └────────────────────────────────────────────────────────┘
                                             ▲
                                             │ same files
                          ┌──────────────────┴──────────────────┐
                          │     External agent CLIs             │
                          │  claude / codex / cursor / antigrv  │
                          └─────────────────────────────────────┘
```

## Data flow

### Ingest a URL

```
POST /api/notebooks/{id}/ingest {url}
       │
       ▼
adapters/url.py  ── fetch + readability + html2text ──▶ raw/<topic>/YYYY-MM-DD-slug.md
       │                                                     │
       │                                              (file write)
       │                                                     │
       │                                                     ▼
       │                                       watchfiles emits "added"
       │                                                     │
       ▼                                                     ▼
agent.runtime dispatches Compile op         index.builder embeds the new raw doc
       │                                                     │
       │  reads SKILL.md, wiki/index.md, related raw          │
       │  decides merge-vs-new                                │
       │                                                     ▼
       ▼                                          embeddings.db gets the chunks
agent edits wiki/<topic>/<article>.md
agent edits wiki/index.md, wiki/log.md
       │
       │  every Edit → file write
       ▼
watchfiles emits "modified"
       │
       ├─▶ index.builder re-embeds the touched wiki page
       │
       └─▶ sse.py publishes agent.tool_call events
                │
                ▼
       Frontend SSE listener updates ActivityStream + ArticleReader
```

### Ask a question

```
POST /api/notebooks/{id}/ask {query}
       │
       ▼
agent.runtime dispatches Query op
       │
       │  reads wiki/index.md (table of contents)
       │  hybrid retrieval: wiki page hits + raw chunk hits via sqlite-vec
       │  picks pages, synthesizes answer
       ▼
returns {answer, citations: [{page_path, anchor, raw_refs}]}
       │
       ▼
Frontend renders streaming answer; citation chips link into Read mode.
On user "Archive" → agent runs Archive op → new wiki page + log entry.
```

### Cross-CLI edit

```
$ cd ~/NotebookAI/notebooks/my-nb && claude
> ingest https://example.com/foo
       │
       ▼
Claude Code uses .claude/skills/karpathy-llm-wiki/SKILL.md verbatim
       │
       ▼
Writes raw/, edits wiki/  (same paths as the in-process agent)
       │
       ▼
watchfiles in NotebookAI's running backend sees the changes
       │
       ▼
IndexBuilder re-embeds; SSE pushes events; UI updates live.
```

## Module boundaries

Every module has one job. Cross-module communication goes through the contracts in `docs/CONTRACTS.md` so each phase could be built and tested in isolation.

### `backend/notebookai/scaffold.py`

Creates the on-disk notebook layout. Idempotent. Owns the directory contract: `.notebookai/`, `.claude/skills/`, `.agents/skills/`, `AGENTS.md`, `README.md`, `raw/`, `wiki/index.md`, `wiki/log.md`, `chats/`. The skill bundle is copied from `skills/karpathy-llm-wiki/`. Optional `git init` happens here.

### `backend/notebookai/adapters/`

Source ingestors. Each adapter (`url.py`, `pdf.py`, `youtube.py`, `topic.py`) implements the `SourceAdapter` protocol from `base.py`: `fetch(input) → RawSource(slug, topic, content_md, frontmatter)`. Adapters never touch the index or the agent — they only return the raw markdown the rest of the pipeline writes to disk.

### `backend/notebookai/index/`

The derived retrieval index.

- `embeddings.py` — wraps `sentence-transformers/bge-small-en-v1.5` (384-dim, ~30 MB on-disk model, runs CPU-only). Lazily loaded singleton.
- `store.py` — sqlite-vec wrapper. One `embeddings.db` per notebook. Tables: `chunks(id, path, anchor, text, embedding)`.
- `builder.py` — chunks markdown, embeds, upserts. Idempotent on `(path, anchor)` so repeated re-runs don't duplicate.
- `watcher.py` — `watchfiles.awatch` driver that calls `IndexBuilder.update_path` on `added`/`modified`, `delete_path` on `removed`.
- `events.py` — typed event payloads (decoupled from FastAPI).

### `backend/notebookai/agent/`

The Claude Agent SDK process per notebook.

- `runtime.py` — `AgentRuntime` lifecycle: spawn the SDK session, plumb in tools, dispatch operations, route tool-call events to the SSE broker.
- `operations.py` — the five named ops: `Compile`, `Cascade`, `Lint`, `Query`, `Archive`. Each is a thin orchestration over Claude tool use; the actual prompts live in `skills/karpathy-llm-wiki/SKILL.md`.
- `tools.py` — the SDK tool surface (`read_file`, `write_file`, `edit_file`, `search_index`, `list_wiki`).
- `events.py` — typed agent events (`tool_call`, `op_start`, `op_finish`, `lint_finding`).
- `passive_watcher.py` — background lint loop. Wakes on a timer or file event, runs `Lint`, emits findings.
- `budget.py` — token/$ accounting. Hard budget per op; user-configurable.
- `lint.py` — non-LLM static checks (orphan pages, missing backlinks, broken wikilinks) that the agent's `Lint` op reads as priors.

### `backend/notebookai/api/`

FastAPI surface.

- `app.py`, `main.py` — uvicorn entrypoint, dependency wiring.
- `routers/` — `notebooks.py`, `ingest.py`, `ask.py`, `wiki.py`, `curate.py`, `git.py`. Routers are thin command dispatchers; logic lives in adapters/agent/index.
- `sse.py` — server-sent events broker; one channel per notebook.
- `dependencies.py` — per-request notebook handle resolution.

### `backend/notebookai/chats/`

Conversation persistence. Each chat is a markdown file under `chats/`. Threading is flat (one file per session); search uses the same embedding index.

### `backend/notebookai/git/`

Optional auto-commit. After every Compile/Archive, write a structured commit (`agent: compile <article>`). Lets users reach for `git log` as a notebook history view.

### `backend/notebookai/library/`

Multi-notebook scanner. `scan_library(root)` walks a configured root and yields `LibraryEntry(name, path, last_modified, source_count, wiki_count)`. Used by the GUI's notebook switcher. No state — re-scanned on demand.

### `frontend/`

Next.js 15 App Router. Three top-level routes (`/read`, `/ask`, `/curate`) plus `/curate/history`. Components are split into pure UI (`components/ui/`) and feature components. Zustand store (`store/`) holds the active-notebook handle, SSE subscriptions, and budget state.

### `desktop/`

Tauri 2 wraps the static-export frontend. The Rust shell launches the Python backend as a sidecar (or expects an externally-running one in dev). Bundle target: `.dmg`, `.msi`, `.AppImage`.

### `skills/karpathy-llm-wiki/`

The agent skill — the source of truth for ingest/compile/cascade/query/archive prompts. Phase-3 scaffolding copies it into every new notebook so external CLIs find it locally.

## Key design decisions

| Decision | Rationale | Cross-ref |
|---|---|---|
| **Files are the database; sqlite is a derived index.** | Lets any tool (Obsidian, VS Code, git) work on the data. Deletes of `.notebookai/` are recoverable. | VISION.md §"Files all the way down" |
| **One long-running agent per notebook, not per request.** | Compile/cascade are multi-step; conversation context within an op matters; a per-request agent would re-read the wiki TOC every time. | VISION.md §"Three layers" |
| **Skill prompts live in `skills/karpathy-llm-wiki/SKILL.md` verbatim, not in code.** | Enables cross-CLI portability. The same SKILL.md drives Claude Code, Codex, Cursor when they `cd` into a notebook. | CONTRACTS.md §"Skill bundle invariants" |
| **sqlite-vec, not Chroma/Qdrant/pgvector.** | Single-file store, zero deps, lives in `.notebookai/embeddings.db` next to its data. Fits the "delete and rebuild" property. | VISION.md §"Technology stack" |
| **`bge-small-en-v1.5` (384-dim).** | CPU-fast (sub-100ms per chunk on M-series), tiny model (~30 MB), on the Pareto frontier for English retrieval. | — |
| **SSE, not WebSockets.** | Agent-stream is one-way; SSE is half the code; reconnects are free. | VISION.md §"Realtime agent visibility" |
| **Tauri 2 over Electron.** | ~10 MB vs. ~100 MB bundle, native webview, Rust shell. The React 19 + static export story works (see `next.config.ts`). | VISION.md open question 1 (resolved) |
| **Chats as markdown.** | Same portability argument as wiki/. Threading is flat per-file, which is fine. | VISION.md open question 2 (resolved) |
| **Background lint optional, on-demand by default.** | Token cost is real. Start cheap; let users opt in per-notebook. | VISION.md open question 3 (resolved) |
| **iCloud / Dropbox / git for sync.** | The user's existing tools work. Don't sync `.notebookai/`. | VISION.md open question 5 (resolved) |
| **No multi-user, no auth, no cloud.** | Local-first is the moat. Auth is what kills weekend projects. | VISION.md §"Non-goals" |

## Performance characteristics

### Embedding model

- **Model:** `BAAI/bge-small-en-v1.5`, 384-dim, ~33 MB on-disk after first download.
- **Throughput (M2/M3 CPU):** ~80–120 chunks/sec for 256-token chunks. A 10 KB markdown page (~5 chunks) embeds in <100 ms.
- **Memory:** ~150 MB RSS for the model + tokenizer.
- **Cold start:** ~1.5 s on first call (model load), then sub-second.

### Index database (sqlite-vec)

- **Per notebook**, one `embeddings.db` file.
- **Scaling:** measured comfortably to ~50k chunks (≈ a few thousand markdown pages) with sub-100 ms top-10 ANN queries on a single thread. Beyond that, partition by topic or add HNSW (sqlite-vec roadmap).
- **Disk:** ~6 KB per chunk including the 384-dim float32 vector and metadata. 50k chunks ≈ 300 MB.
- **Rebuild from scratch:** `IndexBuilder.rebuild()` walks `raw/` + `wiki/` and re-embeds. ~1 minute per 1k chunks on CPU.

### Agent latency

- **Compile op** (one new raw source → one wiki edit): typically 6–15 s with Claude Sonnet 4 — dominated by 1–3 tool round-trips against the wiki TOC + the source itself.
- **Query op** (Ask mode): 2–5 s for a single-page answer; longer for multi-page synthesis. Streaming tokens appear in the UI as they arrive via SSE.
- **Cascade op** (after a wiki edit, propagate to backlinks): bounded by `budget.py`; default cap 4 pages and ~$0.10 per cascade.
- **Lint op** (background): runs on a debounce; static `lint.py` findings are cheap; LLM-backed contradiction checks honor a per-notebook daily budget.

### File watcher

- `watchfiles.awatch` uses FSEvents on macOS, inotify on Linux, ReadDirectoryChangesW on Windows.
- Debounced 200 ms.
- Per-notebook task; idle cost is essentially zero.

### SSE broker

- One channel per notebook, fanned out to N frontend subscribers.
- Backpressure: dropped events on slow consumers (the canonical state is on disk anyway — a refresh re-reads everything).

## Build provenance

NotebookAI was built in 14 isolated phases with frozen contracts. The orchestrator state lives in `.notebookai-build/state.json`; per-phase gate tests live in `.notebookai-build/tests/phase-N.sh`. The cumulative audit (`scripts/audit-notebookai.sh`) re-runs every gate plus the full pytest suite, frontend build, and `ruff` check. See [BUILD.md](../BUILD.md) for the full phase contract and [CONTRACTS.md](CONTRACTS.md) for the frozen symbol-level interfaces.
