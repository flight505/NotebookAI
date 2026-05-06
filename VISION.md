# NotebookAI — Vision

> A local-first, agent-native knowledge workspace. Each notebook is a folder of plain markdown that compounds over time — usable from a polished GUI **and** from any agent CLI (Claude Code, Codex, Antigravity, Cursor) pointed at the same folder.

## Thesis

Most "AI notebook" products treat documents as input and answers as output. The knowledge never accumulates — each query re-derives what the model already figured out last week. NotebookAI flips this: the wiki is the substrate, retrieval is a derived index, and a long-running agent maintains the wiki as new sources arrive. Knowledge compounds. Answers cite durable pages, not transient chunks.

Three properties define the product:

1. **Compounding knowledge.** Synthesis happens at ingest time, not query time. The wiki gets sharper with every source, not bigger.
2. **Files all the way down.** The notebook is a folder of markdown on the user's disk. Portable, git-able, openable in Obsidian or VSCode. The database is a derived cache, not the source of truth.
3. **Agent-portable.** Any agent skill–compatible CLI can operate on the same notebook. NotebookAI is one front-end among several; the notebook itself is the product.

## Reconstructive moves vs. OpenNotebookLM

| | OpenNotebookLM (was) | NotebookAI (is) |
|---|---|---|
| Substrate | Chunks + embeddings in SQLite | Markdown files on disk |
| Citation target | Chunk excerpt | Wiki page (which links to raw + offsets) |
| Orchestration | REST routers contain logic | Long-running agent; routers are commands |
| Memory | Conversation history | The wiki itself |
| Storage role | Source of truth | Derived index, rebuilt on file events |
| External access | API only | Filesystem + API (any agent CLI works) |
| Auth | JWT, multi-user | None — local-first, single user |
| Primary mode | RAG retrieval | Wiki synthesis with retrieval as one tool |

## Directory layout (the product)

The directory layout *is* the API for external agents. It must be stable, conventional, and self-describing.

```
~/NotebookAI/                                    # user-configurable root
├── config.json                                  # global app config
└── notebooks/
    ├── ml-research/                             # one notebook = one workspace
    │   ├── .notebookai/                         # internal, gitignore-able
    │   │   ├── notebook.json                    # id, name, created, schema_version
    │   │   ├── index.db                         # sqlite — projects/jobs/sessions
    │   │   ├── embeddings.db                    # sqlite-vec — derived index
    │   │   └── locks/                           # agent coordination
    │   ├── .claude/skills/karpathy-llm-wiki/    # Claude Code finds it here
    │   ├── .agents/skills/karpathy-llm-wiki/    # agentskills.io standard path
    │   ├── AGENTS.md                            # what this folder is, for any agent
    │   ├── README.md                            # human-readable, agent-maintained
    │   ├── raw/                                 # immutable source material
    │   │   └── <topic>/YYYY-MM-DD-slug.md
    │   ├── wiki/                                # compiled knowledge (LLM-maintained)
    │   │   ├── index.md
    │   │   ├── log.md
    │   │   └── <topic>/<article>.md
    │   └── chats/                               # conversations as markdown
    │       └── 2026-05-06-attention-mechanisms.md
    └── personal-notes/
        └── …
```

Why this layout works for cross-tool access:

- `.claude/skills/` makes Claude Code use the wiki skill automatically when invoked from inside the folder.
- `.agents/skills/` is the [agentskills.io](https://agentskills.io) standard — Cursor, Codex, OpenCode discover it without configuration.
- `AGENTS.md` is the cross-agent convention for "what this folder is" — read first by every agent.
- `README.md` is human-facing (and agent-maintained as a notebook gets bigger).
- The `.notebookai/` folder is the only place internal state lives; deleting it rebuilds from markdown without data loss.

## Architecture

### Three layers

**1. The notebook (filesystem).** Pure markdown + the skill bundle. Source of truth. Editable by any tool. Watched by NotebookAI for change events.

**2. The agent runtime (Claude Agent SDK).** Long-running process per notebook. Owns ingest, compile, cascade-update, lint, query-with-archive. Streams every tool call to the UI. Uses the karpathy-llm-wiki skill verbatim. Local Ollama is *not* used here — the agent loop needs reliable tool-use and multi-step file editing.

**3. The retrieval index (sqlite-vec + sentence-transformers).** Local embedding model rebuilds the vector index on file change. Used by the agent as one tool among many ("search wiki for X") and by the chat UI for fast retrieval. Fully local, no cloud.

### Request flow examples

**Ingest a URL:**

```
GUI → POST /api/notebooks/{id}/ingest {url}
  → backend fetches via url.py adapter, writes raw/topic/YYYY-MM-DD-slug.md
  → backend dispatches agent task: "compile this raw file"
  → Agent SDK: reads SKILL.md, reads index, reads source, decides merge-vs-new
  → Agent edits wiki/ files; cascade updates; updates index.md, log.md
  → file watcher: re-embeds touched wiki pages
  → SSE stream: every tool call surfaces in UI ("editing wiki/ml/transformers.md…")
```

**Ask a question:**

```
GUI → POST /api/notebooks/{id}/ask {query}
  → Agent SDK: skill-driven Query op
  → reads wiki/index.md, picks pages, synthesizes
  → returns {answer, citations: [{page_path, anchor, raw_refs}]}
  → user clicks "Archive" → agent writes new wiki page, appends log
```

**External CLI access:**

```
$ cd ~/NotebookAI/notebooks/ml-research
$ claude
> Ingest https://example.com/attention-paper
   ↓ Claude Code finds .claude/skills/karpathy-llm-wiki, uses it
   ↓ same files updated, NotebookAI GUI reflects changes via watcher
```

### Realtime agent visibility

Server-Sent Events stream from each running agent to its notebook's UI panel. Every tool call (Read, Write, Bash, etc.) appears as a typed event:

```
event: agent.tool_call
data: {"tool": "Edit", "file": "wiki/ml/transformers.md", "preview": "+12 -3"}
```

The Curate panel shows live agent activity, accept/reject prompts for proposed cascade updates, and a stream of contradictions/orphans the agent flags during background lint.

## Surface area

### GUI (the polished product)

Three modes per notebook, plus a top-level notebook switcher:

- **Read.** Browse the wiki. Tree view, article reader with rendered markdown, backlinks, graph view of cross-references, raw-source drawer. Editable in-place; saves write to disk; watcher updates index.
- **Ask.** Chat that cites wiki pages (not chunks). Each citation links into Read mode. Streaming answers. Conversations save to `chats/` as markdown.
- **Curate.** Live agent activity feed. Pending decisions ("merge into Transformers or create new page?"). Lint findings (contradictions, orphans, missing cross-refs). Operation log timeline.

Sources are a side-drawer in all three modes (drag-drop to ingest).

### CLI (the agent integration)

A thin `notebookai` CLI for power users:

```
notebookai new ml-research          # scaffold a notebook folder
notebookai open ml-research         # open in GUI
notebookai ingest <url|file>        # one-shot ingest from terminal
notebookai claude                   # cd + claude with the skill loaded
```

But the bigger story is "no CLI needed" — `cd` and `claude` (or `codex`, etc.) already works because the skill is in `.claude/skills/`.

### External agent integration

The notebook folder is the API. A user can:

- Run `claude` inside the folder → gets karpathy-llm-wiki skill, edits files, GUI updates live.
- Run `codex` → reads `.agents/skills/`, same workflow.
- Open in VSCode + GitHub Copilot Chat → reads `AGENTS.md`, can answer "what's in this notebook" by reading wiki pages.
- Open in Obsidian → markdown renders, backlinks work, no NotebookAI process needed for read-only browsing.

This is the moat. NotebookAI isn't trying to lock the user in; it's the *best* front-end for an open format.

## Technology stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI + watchfiles + Claude Agent SDK | Existing FastAPI carries forward; watchfiles for file→index sync; Agent SDK is the only piece that natively executes Agent Skills. |
| Embeddings | sentence-transformers (`bge-small-en-v1.5`) | Local, fast, already wired up. |
| Vector store | sqlite-vec | Single-file, zero-deps, derived index. |
| Markdown | unified + remark-gfm + custom wikilink/backlink resolver | Obsidian-style `[[wikilinks]]` cross-refs. |
| Frontend | Next.js 15 + React 19 + Tailwind 4 + Zustand + framer-motion | Existing stack; React 19 + RSC where it helps. |
| Realtime | Server-Sent Events | Simpler than WebSockets, agent-stream is one-way. |
| Desktop | **Tauri 2** | Native multi-platform (macOS / Windows / Linux), tiny bundle (~10MB vs Electron's ~100MB), Rust shell, 2025-era SOTA. |
| Packaging | Tauri bundler → `.dmg` / `.msi` / `.AppImage` | One install per platform. |
| LLM (agent) | Claude (Sonnet/Opus) via Agent SDK, Max OAuth | Per global CLAUDE.md, OAuth works for personal use without API key. |
| LLM (cheap retrieval reranking) | Optional local Ollama | Falls back gracefully if not present. |

Mobile is deliberately deferred — the design doesn't compromise around small screens, and the file-based notebook means a user can sync via iCloud/Dropbox to a mobile editor today.

## Non-goals

- Multi-user / team collaboration. (Files in iCloud or git solve this for the local-first user.)
- Cloud hosting / SaaS deployment. (Adds auth, billing, infra; kills local-first.)
- Replacing Obsidian as a daily driver. (NotebookAI is for *agent-maintained* knowledge; Obsidian is for *human-maintained*. They coexist on the same folder.)
- Supporting non-skill-capable models for agent ops. (Local Ollama isn't reliable enough for the multi-step compile loop. Be honest about it.)

## Migration from OpenNotebookLM

What survives: `adapters/{pdf,url,youtube}.py`, `services/embeddings.py`, `services/chunking.py`, the Next.js scaffold, sqlite-vec wiring.

What's deleted: top-level vestigial `app/` (auth, monitoring), JWT auth, multi-user routing, the `Project → Document → Chunk → Conversation → Message` SQLAlchemy hierarchy as primary state, the 4-pane chat-centric layout.

What's new: notebook directory layout, Agent SDK service, file watcher, Curate mode, wiki renderer with backlinks/graph, Tauri desktop shell, cross-CLI skill installation.

## Open questions to settle before the plan

1. **Tauri vs. Electron** — Tauri is technically better (smaller, faster, more SOTA) but the React 19 + Next.js story is slightly less mature there than in Electron. Worth a 1-day spike.
2. **Conversations as markdown vs. SQLite** — leaning markdown for portability, but it complicates threading and search. SQLite is simpler; markdown is the "file-first" purist choice.
3. **Background agent or on-demand?** Always-on background lint that surfaces findings is the demo moment, but it spends Claude tokens. On-demand is cheaper but less magical. Suggest: on-demand by default, background optional per-notebook.
4. **Notebook discovery** — does NotebookAI scan a configured root, or does the user open notebooks one at a time? "Folder of notebooks" feels right for multi-notebook UX.
5. **Sync story** — recommend iCloud Drive / Dropbox / git for sync? Document the conventions (don't sync `.notebookai/`, do sync everything else)?

## Next step

Once these five questions are answered, I'll draft the staged migration plan: which files get deleted, which get repositioned, what gets built in what order, and what the first shippable milestone looks like (suggest: "open a notebook folder in the GUI, ingest one URL, see the wiki page get written live, browse it in Read mode" — single-notebook, no Tauri yet, no Curate mode, but the agent loop and file-watcher and skill bundle all working end-to-end).
