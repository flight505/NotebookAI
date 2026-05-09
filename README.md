# NotebookAI

> A local-first, agent-native knowledge workspace where every notebook is a folder of plain markdown that compounds over time.

<!--
  Banner / screenshot placeholder.
  Drop product screenshots here when ready:
    docs/img/notebookai-read-mode.png
    docs/img/notebookai-curate-mode.png
    docs/img/notebookai-tauri-shell.png
-->

## What it is

NotebookAI is a desktop research notebook that treats the **filesystem as the source of truth**. Each notebook is a directory of markdown files — `raw/` for ingested sources, `wiki/` for synthesized articles, `chats/` for conversations — and a long-running agent maintains the wiki as new sources arrive. Knowledge accumulates: every ingest sharpens the wiki instead of inflating a chunk store. Answers cite durable wiki pages, not transient passages.

It is **agent-native**. The notebook directory ships its own agent skill (`karpathy-llm-wiki`) installed at the agentskills.io standard paths (`.claude/skills/`, `.agents/skills/`), so any skill-aware CLI — Claude Code, Codex, Cursor, Antigravity — can operate on the same files NotebookAI's GUI renders. Run `cd notebooks/my-nb && claude` and the assistant immediately knows how to ingest sources, compile wiki pages, and lint the notebook. The polished GUI is one front-end among several; the folder is the product.

It is **local-first**. The Claude Agent SDK runs against the user's own Max OAuth or `ANTHROPIC_API_KEY`. Embeddings (`bge-small-en-v1.5`) and the vector store (`sqlite-vec`) are entirely on-device. Notebooks sync over iCloud Drive, Dropbox, or git — there is no cloud, no auth, no multi-user model. Delete `.notebookai/` and the markdown still loads cleanly in Obsidian.

## Why it's different

| Axis | NotebookLM | Obsidian | **NotebookAI** |
|---|---|---|---|
| Storage substrate | Cloud chunks + embeddings | Markdown files on disk | **Markdown files on disk** |
| Citation target | Source passage | Manual `[[link]]` | **Wiki page (links back to raw + offsets)** |
| Agent model | Server RAG, no agent loop | None native (plugin-driven) | **Long-running Claude Agent SDK process** |
| Sync | Google account | Obsidian Sync / git / iCloud | **Any folder-sync tool (iCloud, Dropbox, git)** |
| Multi-CLI | None | None | **Claude Code, Codex, Cursor, Antigravity via shared skill bundle** |

## Install

**Prerequisites**

- Python 3.10+
- Node 18+ and `pnpm`
- Rust + `cargo` (only required to build the Tauri 2 desktop shell; web frontend works without it)
- Either Claude Max OAuth (recommended for personal use) **or** `ANTHROPIC_API_KEY`
- `uv` for Python package management

**Install steps**

```bash
git clone https://github.com/flight505/NotebookAI.git
cd NotebookAI

# Backend
cd backend && uv sync && cd ..

# Frontend
cd frontend && pnpm install && cd ..

# (Optional) Desktop shell
cd desktop && pnpm install && cd ..
```

## Quick start

Scaffold a notebook, run the dev stack, ingest a URL, and watch the wiki page appear in Read mode.

```bash
# 1. Scaffold a fresh notebook in ~/NotebookAI/notebooks/
cd backend && uv run notebookai new ml-research

# 2. Start the FastAPI backend (file watcher + agent runtime + SSE)
cd backend && uv run notebookai serve &

# 3. Start the Next.js frontend
cd frontend && pnpm dev

# 4. Ingest a URL via the API
curl -X POST http://localhost:8765/api/notebooks/ml-research/ingest \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://lilianweng.github.io/posts/2023-06-23-agent/"}'

# 5. Open http://localhost:3000 → Read mode → watch the wiki page render live
```

## Architecture

NotebookAI has three layers: the **notebook on disk** (source of truth), the **agent runtime** (Claude Agent SDK process per notebook), and the **derived index** (sentence-transformers + sqlite-vec). A file watcher bridges the first two so external edits — including those made by another CLI — immediately re-embed and re-stream into the UI.

For the full stack diagram, data flow, module boundaries, and design-decision rationale, see [`docs/architecture.md`](docs/architecture.md). For the product thesis and reconstructive moves vs. OpenNotebookLM, see [`VISION.md`](VISION.md). For exact symbol-level contracts every phase had to satisfy, see [`docs/CONTRACTS.md`](docs/CONTRACTS.md).

## Cross-CLI

NotebookAI notebooks are agent-portable. The skill bundle is installed both at `.claude/skills/karpathy-llm-wiki/` (Claude Code) and `.agents/skills/karpathy-llm-wiki/` (the [agentskills.io](https://agentskills.io) standard, picked up by Codex, Cursor, Antigravity, OpenCode). An `AGENTS.md` at the notebook root describes the layout in cross-agent prose.

```bash
cd ~/NotebookAI/notebooks/my-nb
claude          # Claude Code finds .claude/skills/karpathy-llm-wiki/
codex           # Codex finds .agents/skills/karpathy-llm-wiki/
# Either CLI can ingest sources, compile wiki pages, run cascade-update.
# The NotebookAI GUI watches the same files and reflects changes live.
```

`scripts/verify-cross-cli.sh` scaffolds a fresh notebook and walks the operator through proving this property end-to-end with a CLI of their choice.

## Build status

| Phase | Title | Status |
|---|---|---|
| 0 | Preflight & repo skeleton | green |
| 1 | Spec lock-in (`docs/CONTRACTS.md`) | green |
| 2 | Skill bundle | green |
| 3 | Notebook scaffold module | green |
| 4 | Derived index + file watcher | green |
| 5 | Source adapters (port) | green |
| 6 | Wiki agent (Claude Agent SDK) | green |
| 7 | FastAPI surface + SSE | green |
| 8 | Frontend shell + Read mode | green |
| 9 | Ask mode | green |
| 10 | Curate mode + scheduled lint | green |
| 11 | Git integration | green |
| 12 | Tauri 2 desktop shell | green |
| 13 | Multi-notebook library + cross-CLI verification | green |
| 14 | Polish + audit | green |

## Project structure

```
NotebookAI/
├── BUILD.md                  # multi-phase build provenance
├── VISION.md                 # product thesis
├── README.md
├── archive/                  # prior-art reference repos (read-only)
├── backend/                  # FastAPI + Claude Agent SDK + watchfiles + sqlite-vec
│   └── notebookai/
│       ├── adapters/         # url, pdf, youtube, topic
│       ├── agent/            # runtime, operations, lint, passive_watcher, budget, tools, events
│       ├── api/              # FastAPI app, SSE, routers
│       ├── chats/            # conversation persistence
│       ├── git/              # git auto-commit integration
│       ├── index/            # embeddings + sqlite-vec + watcher
│       ├── library/          # multi-notebook scanner
│       └── scaffold.py       # `notebookai new` notebook layout writer
├── desktop/                  # Tauri 2 shell wrapping the frontend
│   └── src-tauri/
├── docs/
│   ├── CONTRACTS.md          # frozen symbol-level contracts (Phase 1)
│   └── architecture.md       # stack diagram + data flow + module boundaries
├── frontend/                 # Next.js 15 + React 19 + Tailwind 4 + Zustand
│   ├── app/                  # Read / Ask / Curate / History routes
│   └── components/           # ArticleReader, GraphView, LibraryPanel, ActivityStream, …
├── scripts/
│   ├── audit-notebookai.sh   # full repo audit (this file)
│   └── verify-cross-cli.sh   # interactive cross-CLI portability proof
├── skills/karpathy-llm-wiki/ # the agent skill bundle scaffold sources install from
└── .notebookai-build/        # build orchestrator state + per-phase gate tests
```

## Development

```bash
# Run the full backend test suite (skips tests that need a live Claude session)
cd backend && uv run pytest tests/ -m "not requires_claude"

# Lint the backend
cd backend && uv run ruff check

# Run the frontend in dev mode (Turbopack)
cd frontend && pnpm dev

# Build the frontend (static export — what Tauri ships)
cd frontend && pnpm build

# Run the Tauri desktop shell in dev
cd desktop && pnpm tauri dev

# Run the full repo audit (every phase test + pytest + frontend build + ruff)
bash scripts/audit-notebookai.sh
```

The audit script is also available as a Claude Code skill — say "run the notebookai audit" inside a Claude session and it will invoke `audit-notebookai` and surface the output.

## License

MIT (placeholder — change to your preferred license).
