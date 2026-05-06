# NotebookAI — CONTRACTS

> Binding spec. Phase 2+ phases read this file as their source of truth. Every type, path, and event name here is normative. If a later phase needs to deviate, it amends this file in the same PR.

## Decisions

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Desktop shell | Tauri 2 | ~10 MB bundles, native webviews, OS polish. Spike in Phase 12 if React 19 + Tailwind 4 friction. |
| 2 | Conversations storage | Markdown canonical, SQLite derived | Files-all-the-way-down; external-CLI greppable. |
| 3 | Agent operation mode | On-demand active ops + scheduled Haiku lint + local passive watcher | Magic without runaway cost; visible budget cap. |
| 4 | Notebook discovery | Library pattern (scan ~/NotebookAI/notebooks/) | Matches Obsidian/VSCode mental model; supports external notebook registration. |
| 5 | Sync story | Git first-class, iCloud/Dropbox/Syncthing as fallback | Every agent op = one commit; operation log = `git log` rendered. |
| 6 | Embedding scope | Wiki pages first, raw chunks second | Aligns retrieval with the substrate; ~10× smaller index. |

**(1) Tauri 2 shapes Phase 12 (desktop packaging) and Phase 5 (frontend dev shell).** The dev shell is plain Next.js until Phase 12 wraps it. All IPC between frontend and backend stays HTTP+SSE rather than Tauri commands so the same web UI runs in-browser for development and inside Tauri for distribution. If the React 19 + Tailwind 4 webview story bites, Phase 12 has a documented fallback (Tauri 2 with disabled JIT, or a pinned Tailwind 3.4 fallback) but no Electron escape hatch is approved.

**(2) Markdown-canonical conversations shape Phase 4 (notebook scaffolding) and Phase 8 (Ask router).** Each chat is one file under `chats/YYYY-MM-DD-slug.md` with front-matter for `id`, `created_at`, `model`, `notebook_id`. The SQLite `chats` table is rebuilt from disk on startup and on file-watcher events; deleting `index.db` and restarting must produce identical query results. No code path may treat SQLite as canonical for chat content — only for derived columns (FTS, vector refs, last_message_at).

**(3) Three-mode agent operation shapes Phase 6 (Agent SDK service) and Phase 7 (FileWatcher).** Active ops run synchronously per user request and stream over SSE. Scheduled Haiku lint runs from a per-notebook cron (default: hourly while NotebookAI is running, idle if no recent edits) under a token budget cap (default: 50k input / 10k output per day, configurable in `config.json`). The passive watcher is local-only — it computes embeddings, dirties the index, and never spends LLM tokens on its own. The agent runtime never escalates passive watcher events to active ops without an explicit user "Apply" click in Curate mode.

**(4) Library pattern shapes Phase 4 (scaffolding) and Phase 11 (notebook switcher UI).** The library is `~/NotebookAI/notebooks/` by default; users may register external paths via `config.json` `extra_notebook_roots`. A folder is treated as a notebook iff it contains `.notebookai/notebook.json`. Notebook discovery is a directory scan plus the registered roots; no central database tracks which notebooks exist. Deleting a notebook means deleting the folder.

**(5) Git-first sync shapes Phase 9 (operation log) and Phase 10 (Curate mode).** Every agent op produces exactly one commit on `main`. The operation log surfaced in Curate is `git log --pretty=%H%n%an%n%s%n%b -- .` rendered as a timeline. Users who do not want git can disable per-notebook with `notebook.json.git_enabled = false`; in that mode the operation log is read from `.notebookai/oplog.jsonl` instead. iCloud/Dropbox/Syncthing remain supported but the canonical history lives in `.git/`.

**(6) Wiki-first embedding shapes Phase 3 (embeddings service) and Phase 8 (Ask).** Embedding rows have `kind` ∈ {`wiki`, `raw_chunk`}. Wiki pages embed at full-page granularity (one row per `wiki/**/*.md`). Raw documents stay un-embedded by default; ingest writes raw + immediately compiles into wiki, so wiki coverage tracks raw coverage. Raw-chunk embeddings are produced lazily only when the agent flags a wiki page as "thin" (low coverage of its source) and explicitly requests fine-grained recall. This keeps the index ~10× smaller than OpenNotebookLM and aligns retrieval with what gets cited.

### Cross-decision invariants

The six decisions above produce four invariants that every later phase enforces:

1. **Filesystem is source of truth.** Deleting `.notebookai/` and restarting reproduces identical query results. No code path may treat SQLite as canonical for content (chats, wiki, raw). Tests in Phase 7 assert this round-trip.
2. **Every agent op = one commit (when git enabled).** The orchestrator's per-phase commit (Phase 1 commits this CONTRACTS.md) and the runtime agent's per-op commit share the same template. There is exactly one writer to `.git/` at a time, gated by `.notebookai/locks/git.lock`.
3. **No tool reaches outside the notebook root.** The Bash allowlist, the Write/Edit path check, and the WebFetch gate all enforce this. The single exception is `NotebookList`, which is read-only and only exposes `id`, `name`, `path`.
4. **No background LLM spend without an explicit budget cap.** Lint runs Haiku within `agent.lint_budget_tokens_per_day`. The passive watcher never calls an LLM. Active ops are user-triggered. Phase 6's tests assert that token usage during a no-user-input idle window is zero.

## Notebook Directory Schema

A notebook is a folder with the following layout. The folder is the API for external agents — every name and convention here is normative.

```
~/NotebookAI/notebooks/<id>/                    # <id> is kebab-case; matches notebook.json id
├── .notebookai/                                # internal state; safe to delete (rebuilds)
│   ├── notebook.json                           # canonical notebook metadata (see schema below)
│   ├── index.db                                # sqlite — projects/jobs/sessions/chats derived
│   ├── embeddings.db                           # sqlite-vec — derived vector index
│   ├── oplog.jsonl                             # operation log when git_enabled=false
│   └── locks/                                  # advisory file locks for agent coordination
│       └── compile.lock                        # held while a compile op is running
├── .claude/skills/karpathy-llm-wiki/           # Claude Code finds skill here automatically
│   └── SKILL.md                                # symlink or copy of skill bundle
├── .agents/skills/karpathy-llm-wiki/           # agentskills.io standard discovery path
│   └── SKILL.md                                # same skill, different discovery convention
├── .gitignore                                  # ignores .notebookai/index.db, .notebookai/embeddings.db, .notebookai/locks/
├── AGENTS.md                                   # for any agent: what this folder is, how to operate
├── README.md                                   # human-readable overview, agent-maintained
├── raw/                                        # immutable source material; never edited after ingest
│   └── <topic>/<YYYY-MM-DD>-<slug>.md          # one source = one file; front-matter has url/source
├── wiki/                                       # compiled knowledge; LLM-maintained, human-editable
│   ├── index.md                                # top-level table of contents; backlink hub
│   ├── log.md                                  # human-readable operation log (one bullet per op)
│   └── <topic>/<article>.md                    # synthesized articles with [[wikilinks]]
└── chats/                                      # conversations as markdown (canonical)
    └── <YYYY-MM-DD>-<slug>.md                  # one chat = one file
```

### `.notebookai/notebook.json`

The single source of truth for notebook identity. Written at scaffold time, mutated only by the backend.

```jsonc
{
  "id": "ml-research",                       // kebab-case; matches folder name; immutable
  "name": "ML Research",                     // human display name; mutable
  "created_at": "2026-05-06T14:22:08Z",      // RFC3339 UTC; immutable
  "schema_version": 1,                       // bump on breaking layout changes
  "git_enabled": true,                       // false → use .notebookai/oplog.jsonl instead
  "agent": {
    "model": "claude-sonnet-4-6",            // active-op model
    "lint_model": "claude-haiku-4-5-20251001",          // scheduled-lint model
    "lint_schedule": "hourly",               // hourly | daily | off
    "lint_budget_tokens_per_day": 50000      // hard cap on lint input tokens
  },
  "embeddings": {
    "model": "bge-small-en-v1.5",            // sentence-transformers model id
    "dim": 384                                // must match model
  },
  "description": "Notes and synthesis on ML research papers."  // optional; surfaced in library
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `str` (kebab-case, `^[a-z0-9-]{1,64}$`) | yes | Immutable. Must equal folder basename. |
| `name` | `str` (1..120) | yes | Mutable. Display name. |
| `created_at` | `datetime` (RFC3339 UTC) | yes | Immutable. Set at scaffold. |
| `schema_version` | `int` (≥1) | yes | Currently `1`. |
| `git_enabled` | `bool` | yes | Default `true`. |
| `agent.model` | `str` | yes | Default `"claude-sonnet-4-6"`. |
| `agent.lint_model` | `str` | yes | Default `"claude-haiku-4-5-20251001"`. |
| `agent.lint_schedule` | `Literal["hourly","daily","off"]` | yes | Default `"hourly"`. |
| `agent.lint_budget_tokens_per_day` | `int` (≥0) | yes | Default `50000`. |
| `embeddings.model` | `str` | yes | Default `"bge-small-en-v1.5"`. |
| `embeddings.dim` | `int` (≥1) | yes | Must match model output. |
| `description` | `str` (0..512) | no | Optional. |

### `AGENTS.md` content convention

Auto-generated at scaffold; agent-maintained on schema bumps. Sections are case-sensitive H2s. Required sections:

- `## What this is` — one paragraph: "This is a NotebookAI notebook. The wiki/ directory is the substrate. raw/ is immutable. chats/ is conversation history."
- `## Operating principles` — three bullets: (1) edit `wiki/` not `raw/`; (2) use the karpathy-llm-wiki skill for compile/cascade; (3) every op is one commit.
- `## Layout` — copy of the directory tree above, scoped to this notebook.
- `## Skill` — pointer to `.claude/skills/karpathy-llm-wiki/SKILL.md` and `.agents/skills/karpathy-llm-wiki/SKILL.md`.
- `## Do not edit` — files the agent must not touch: `raw/**`, `.notebookai/index.db`, `.notebookai/embeddings.db`, `.git/**`.

### `README.md` content convention

Human-facing. Auto-generated at scaffold with sections: `# <name>`, short description, "Recent activity" (last 5 wiki edits, mirror of `wiki/log.md` tail), "Top topics" (top 5 `wiki/<topic>/` directories by article count). Regenerated by the agent after every successful `compile` or `cascade` op. Hand-edits between agent runs are preserved by replacing only the auto-generated marker block delimited by `<!-- notebookai:auto-start -->` … `<!-- notebookai:auto-end -->`.

## REST API surface

All endpoints live under `/api`. JSON over HTTP. SSE under `text/event-stream`. No auth (single-user, local-first). All routers mount on the FastAPI app in `backend/app/main.py`.

### Router: `notebooks`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `GET` | `/api/notebooks` | — | `Notebook[]` | List all notebooks discovered in library + extra roots. |
| `POST` | `/api/notebooks` | `{ name: string, id?: string, description?: string }` | `Notebook` | Scaffold a new notebook folder. If `id` omitted, derive from `name`. |
| `GET` | `/api/notebooks/{id}` | — | `Notebook` | Get single notebook metadata. 404 if not found. |
| `PATCH` | `/api/notebooks/{id}` | `Partial<NotebookMutable>` | `Notebook` | Update mutable fields (`name`, `description`, `agent.*`). |
| `DELETE` | `/api/notebooks/{id}` | — | `{ deleted: true }` | Move folder to `~/NotebookAI/.trash/<id>-<timestamp>/`. Never `rm -rf`. |

```ts
type Notebook = {
  id: string;
  name: string;
  path: string;                       // absolute filesystem path
  created_at: string;                 // RFC3339
  schema_version: number;
  git_enabled: boolean;
  agent: { model: string; lint_model: string; lint_schedule: "hourly"|"daily"|"off"; lint_budget_tokens_per_day: number };
  embeddings: { model: string; dim: number };
  description?: string;
  stats: { raw_count: number; wiki_count: number; chat_count: number; last_op_at: string | null };
};
type NotebookMutable = Pick<Notebook, "name" | "description" | "agent">;
```

### Router: `library`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `GET` | `/api/library` | — | `LibraryEntry[]` | Library view: same as `GET /api/notebooks` plus library root info. |
| `POST` | `/api/library/register` | `{ path: string }` | `LibraryEntry` | Register an external folder as a notebook (must contain `.notebookai/notebook.json`). |
| `DELETE` | `/api/library/register` | `{ path: string }` | `{ unregistered: true }` | Remove from `extra_notebook_roots`; folder untouched. |

```ts
type LibraryEntry = Notebook & { is_external: boolean; root: string };
```

### Router: `ingest`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `POST` | `/api/notebooks/{id}/ingest/url` | `{ url: string, topic?: string }` | `IngestJob` | Fetch URL via `adapters/url.py`, write to `raw/<topic>/`, dispatch compile op. |
| `POST` | `/api/notebooks/{id}/ingest/file` | `multipart/form-data: file, topic?` | `IngestJob` | Save uploaded file to `raw/<topic>/`, run adapter, dispatch compile. |
| `POST` | `/api/notebooks/{id}/ingest/youtube` | `{ url: string, topic?: string }` | `IngestJob` | Fetch transcript via `adapters/youtube.py`, write raw, dispatch compile. |
| `GET` | `/api/notebooks/{id}/ingest/{job_id}` | — | `IngestJob` | Poll job status. Most clients use SSE instead. |

```ts
type IngestJob = {
  id: string;                                       // ULID
  notebook_id: string;
  kind: "url" | "file" | "youtube";
  source: string;                                   // url, filename, or youtube id
  topic: string;
  raw_path: string;                                 // relative to notebook root
  status: "queued" | "fetching" | "compiling" | "done" | "error";
  error?: string;
  started_at: string;
  finished_at?: string;
};
```

### Router: `ask`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `POST` | `/api/notebooks/{id}/ask` | `{ query: string, chat_id?: string }` | `text/event-stream` | Streams agent answer with citations. Appends to `chats/<date>-<slug>.md`. |
| `POST` | `/api/notebooks/{id}/ask/archive` | `{ chat_id: string, message_id: string }` | `{ wiki_path: string }` | Promote a chat answer into a new wiki article; agent writes the page. |

The streaming response uses the `agent.*` SSE event types (see next section). When the stream ends, the final message includes `citations: Citation[]`.

```ts
type Citation = {
  wiki_path: string;                                // e.g. "wiki/ml/transformers.md"
  anchor?: string;                                  // optional heading id
  raw_refs: { raw_path: string; offset_start: number; offset_end: number }[];
};
```

### Router: `lint`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `POST` | `/api/notebooks/{id}/lint` | `{ scope?: "all"|"recent" }` | `{ job_id: string }` | Trigger an on-demand lint pass (Haiku). Streams findings via SSE. |
| `GET` | `/api/notebooks/{id}/lint/findings` | `?status=open|resolved` | `LintFinding[]` | List lint findings in `.notebookai/index.db.lint_findings`. |
| `POST` | `/api/notebooks/{id}/lint/findings/{finding_id}/resolve` | `{ action: "accept"|"reject"|"defer" }` | `LintFinding` | Update finding status. `accept` may dispatch an active fix op. |

```ts
type LintFinding = {
  id: string;
  notebook_id: string;
  kind: "contradiction" | "orphan" | "missing_xref" | "thin_coverage" | "stale_link";
  severity: "info" | "warn" | "error";
  wiki_paths: string[];
  message: string;
  suggested_fix?: string;
  status: "open" | "accepted" | "rejected" | "deferred";
  created_at: string;
};
```

### Router: `articles`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `GET` | `/api/notebooks/{id}/articles` | `?topic=&q=` | `Article[]` | List wiki pages. Optional topic filter and FTS query. |
| `GET` | `/api/notebooks/{id}/articles/{path:path}` | — | `Article` | Read one article. `path` is wiki-relative (e.g. `ml/transformers.md`). |
| `PUT` | `/api/notebooks/{id}/articles/{path:path}` | `{ content: string }` | `Article` | Write article. Triggers `wiki.modified` watcher event and one commit (`[human-edit]`). |
| `DELETE` | `/api/notebooks/{id}/articles/{path:path}` | — | `{ deleted: true }` | Move to `.notebookai/.trash/wiki/`; commit (`[archive]`). |

```ts
type Article = {
  path: string;                                     // wiki-relative
  title: string;
  content: string;
  frontmatter: Record<string, unknown>;
  backlinks: string[];                              // other wiki paths that link here
  outlinks: string[];                               // wiki paths this article links to
  raw_refs: string[];                               // raw paths cited in body
  updated_at: string;
};
```

### Router: `log`

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `GET` | `/api/notebooks/{id}/log` | `?limit=100&since=<rfc3339>` | `OpLogEntry[]` | Operation log entries (most-recent-first). Backed by git when enabled, by `oplog.jsonl` otherwise. |

```ts
type OpLogEntry = {
  id: string;                                       // git SHA or jsonl ULID
  op: "ingest" | "compile" | "cascade" | "archive" | "lint-fix" | "human-edit";
  summary: string;
  files_changed: string[];
  author: "agent" | "human";
  created_at: string;
};
```

### Router: `history` (git)

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `GET` | `/api/notebooks/{id}/history` | `?path=&limit=` | `Commit[]` | `git log` for the notebook (or one path). 409 if `git_enabled=false`. |
| `GET` | `/api/notebooks/{id}/history/{sha}` | — | `CommitDetail` | One commit with diff. |
| `GET` | `/api/notebooks/{id}/history/{sha}/diff/{path:path}` | — | `text/plain` | Unified diff for one file at a commit. |

```ts
type Commit = { sha: string; author: string; subject: string; body: string; created_at: string; files_changed: string[] };
type CommitDetail = Commit & { diff: string };
```

### Router: `events` (SSE)

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| `GET` | `/api/notebooks/{id}/events` | `?since=<event_id>` | `text/event-stream` | Subscribe to all notebook events: agent.*, ingest.*, lint.*, file.*, commit.*. |

The `since` query parameter resumes after a known event id. Server keeps a 1000-entry ring buffer per notebook for resumption.

## SSE event types

All events stream over `GET /api/notebooks/{id}/events` and over the per-request `POST /api/notebooks/{id}/ask` stream. SSE format: `id: <ulid>\nevent: <name>\ndata: <json>\n\n`. Every event payload includes a top-level `notebook_id: string`.

| `event:` | When it fires | `data:` shape |
|---|---|---|
| `agent.tool_call` | Agent SDK invokes a tool (Read, Write, Edit, Bash, Grep, Glob, WebFetch, NotebookList, ArticleResolve, BacklinkSearch). One event per call, before execution. | `{ notebook_id, op_id, tool, input, preview? }` |
| `agent.tool_result` | The same tool call returns. | `{ notebook_id, op_id, tool, ok, summary, error? }` |
| `agent.message` | Agent emits a streaming text chunk to the user. | `{ notebook_id, op_id, role: "assistant", delta: string }` |
| `agent.done` | Agent op finishes successfully. | `{ notebook_id, op_id, op, citations?: Citation[], commit_sha?: string }` |
| `agent.error` | Agent op fails or is cancelled. | `{ notebook_id, op_id, op, error: string, retriable: boolean }` |
| `ingest.started` | Ingest job accepted; fetch beginning. | `{ notebook_id, job_id, kind, source }` |
| `ingest.complete` | Ingest job finished; raw file written; compile dispatched. | `{ notebook_id, job_id, raw_path, op_id }` |
| `lint.finding` | A lint pass produces a finding. | `{ notebook_id, finding: LintFinding }` |
| `file.changed` | Watcher debounce fires for any file under notebook. | `{ notebook_id, path, kind: "added"\|"modified"\|"deleted", scope: "raw"\|"wiki"\|"chats"\|"meta" }` |
| `commit.created` | A git commit was just written. | `{ notebook_id, sha, op, summary, files_changed }` |

Cross-references: the `tool` field of `agent.tool_call` matches a name in the AgentTool inventory below. The `Citation` shape on `agent.done` matches the `Citation` type in the `ask` router. The `LintFinding` shape matches the `lint` router.

`op_id` is a per-operation ULID. Multiple events from the same op share an `op_id` so the UI can group them. The `op` field on `agent.done`/`agent.error` is one of: `ingest`, `compile`, `cascade`, `archive`, `lint-fix`, `ask`.

### Wire format example

A complete `compile` op as it appears on the SSE stream (one event per line block):

```
id: 01HW3K7YQF3Z9XS0M2N6P8R4VB
event: agent.tool_call
data: {"notebook_id":"ml-research","op_id":"01HW3K7YQF3Z9XS0M2N6P8R4VB","tool":"Read","input":{"path":"wiki/index.md"}}

id: 01HW3K7YQG3Z9XS0M2N6P8R4VC
event: agent.tool_result
data: {"notebook_id":"ml-research","op_id":"01HW3K7YQF3Z9XS0M2N6P8R4VB","tool":"Read","ok":true,"summary":"# Index\n\n- ML\n  - …"}

id: 01HW3K7YQH3Z9XS0M2N6P8R4VD
event: agent.tool_call
data: {"notebook_id":"ml-research","op_id":"01HW3K7YQF3Z9XS0M2N6P8R4VB","tool":"Write","input":{"path":"wiki/ml/transformers.md","content":"# Transformers\n…"},"preview":"+412 -0"}

id: 01HW3K7YQJ3Z9XS0M2N6P8R4VE
event: agent.message
data: {"notebook_id":"ml-research","op_id":"01HW3K7YQF3Z9XS0M2N6P8R4VB","role":"assistant","delta":"Wrote wiki/ml/transformers.md "}

id: 01HW3K7YQK3Z9XS0M2N6P8R4VF
event: commit.created
data: {"notebook_id":"ml-research","sha":"b3a91e2","op":"compile","summary":"add wiki/ml/transformers.md from attention-is-all-you-need.pdf","files_changed":["wiki/ml/transformers.md","wiki/index.md","wiki/log.md"]}

id: 01HW3K7YQL3Z9XS0M2N6P8R4VG
event: agent.done
data: {"notebook_id":"ml-research","op_id":"01HW3K7YQF3Z9XS0M2N6P8R4VB","op":"compile","commit_sha":"b3a91e2"}
```

### Pydantic models (backend)

```python
from typing import Literal, Optional
from pydantic import BaseModel

class AgentToolCall(BaseModel):
    notebook_id: str
    op_id: str
    tool: Literal["Read","Write","Edit","Glob","Grep","Bash","WebFetch","NotebookList","ArticleResolve","BacklinkSearch"]
    input: dict
    preview: Optional[str] = None

class AgentToolResult(BaseModel):
    notebook_id: str
    op_id: str
    tool: str
    ok: bool
    summary: str
    error: Optional[str] = None

class AgentMessage(BaseModel):
    notebook_id: str
    op_id: str
    role: Literal["assistant"]
    delta: str

class AgentDone(BaseModel):
    notebook_id: str
    op_id: str
    op: Literal["ingest","compile","cascade","archive","lint-fix","ask"]
    citations: Optional[list[dict]] = None
    commit_sha: Optional[str] = None

class AgentError(BaseModel):
    notebook_id: str
    op_id: str
    op: str
    error: str
    retriable: bool

class FileChanged(BaseModel):
    notebook_id: str
    path: str
    kind: Literal["added","modified","deleted"]
    scope: Literal["raw","wiki","chats","meta"]

class CommitCreated(BaseModel):
    notebook_id: str
    sha: str
    op: str
    summary: str
    files_changed: list[str]
```

## Subagent Return Schema

Every build-phase subagent returns its final message in this exact shape:

```
## PHASE-<N>-REPORT
status: pass | fail | partial
files_written: ["path1", "path2", ...]
files_modified: ["path1", ...]
files_unexpected: []
notes: "<2-5 sentences>"
verify_hint: "<command>"
```

This exists because the orchestrator parses subagent output deterministically. The orchestrator runs `phase-<N>.sh` to verify, but it also reads this report to (a) decide whether to commit, (b) populate `.notebookai-build/state.json`, and (c) print a human-readable summary of what just happened. Free-form text outside this block is ignored. The block is anchored on the `## PHASE-<N>-REPORT` heading and parsed line-by-line until the next blank-line-followed-by-non-`field:` line.

Field guarantees: `status` is one of three literal strings; the orchestrator treats anything else as `fail`. `files_written` is the list of files the subagent created from scratch in this run — every entry must exist on disk after the run, and no entry may pre-exist in the previous git commit. `files_modified` is the list of files the subagent edited but did not create — every entry must have a non-zero diff against the previous commit. `files_unexpected` is the list of files the subagent touched outside its declared scope; this list should always be empty for a passing phase. `notes` is 2–5 sentences of plain English describing judgment calls — what was assumed, what was deferred, what the next phase should know. `verify_hint` is the exact bash command (usually `bash .notebookai-build/tests/phase-<N>.sh`) the orchestrator should run to confirm.

A contract violation is any of: status not in {pass, fail, partial}; declared `files_written` that doesn't exist on disk; declared `files_modified` with no diff; non-empty `files_unexpected`; missing `## PHASE-<N>-REPORT` header; report appearing inside another fenced code block; report not being the last block in the message. On violation the orchestrator marks the phase failed in `state.json`, leaves the working tree untouched (no commit), and surfaces the parse error to the user.

### Example reports

Pass:

```
## PHASE-3-REPORT
status: pass
files_written: ["backend/app/services/embeddings.py", "backend/app/services/embeddings_test.py"]
files_modified: ["backend/app/main.py"]
files_unexpected: []
notes: "Wired sentence-transformers via a lazy singleton so cold start stays under 300ms. Tests cover the wiki-page-granularity path; raw-chunk lazy path is stubbed and gated behind a flag for Phase 8."
verify_hint: "bash .notebookai-build/tests/phase-3.sh"
```

Partial (work happened but the verify command does not yet pass):

```
## PHASE-7-REPORT
status: partial
files_written: ["backend/app/services/watcher.py"]
files_modified: []
files_unexpected: []
notes: "Watcher emits raw.* and wiki.* events correctly but chats.* is missing because the watchfiles include glob does not yet cover chats/. Will fix in Phase 7b before next phase runs."
verify_hint: "bash .notebookai-build/tests/phase-7.sh"
```

Fail:

```
## PHASE-5-REPORT
status: fail
files_written: []
files_modified: []
files_unexpected: []
notes: "Could not scaffold Next.js 15 + React 19 against pinned Tailwind 4 alpha; npm install fails on @tailwindcss/postcss. Need to pin Tailwind 3.4 or upgrade Node to 22.x before retrying."
verify_hint: ""
```

## AgentTool inventory

The wiki agent (Claude Agent SDK, `claude-sonnet-4-6` by default) gets the tool surface below when it runs against a notebook. All tools have their `cwd` locked to the notebook root; absolute paths outside the notebook are rejected. Read/Write/Edit/Glob/Grep are stock Claude Agent SDK tools; Bash and WebFetch are gated; NotebookList/ArticleResolve/BacklinkSearch are NotebookAI-specific.

| Name | Description | Input schema | Scope restrictions |
|---|---|---|---|
| `Read` | Read a UTF-8 file from the notebook. | `{ path: string, offset?: number, limit?: number }` | Path must resolve under notebook root. Binary files rejected. Max 2 MB per call. |
| `Write` | Create or overwrite a file. | `{ path: string, content: string }` | Path must resolve under notebook root. `raw/**` is read-only. `.notebookai/index.db`, `.notebookai/embeddings.db`, `.git/**` are read-only. |
| `Edit` | String-replace or unified-diff edit a file. | `{ path: string, old_string: string, new_string: string, replace_all?: boolean }` | Same write restrictions as `Write`. Fails if `old_string` not unique unless `replace_all`. |
| `Glob` | Glob over notebook files. | `{ pattern: string }` | Pattern is rooted at notebook root. Returns up to 1000 matches. |
| `Grep` | Search file contents. | `{ pattern: string, path?: string, glob?: string, output_mode?: "content"\|"files_with_matches"\|"count" }` | Path/glob constrained to notebook root. Uses ripgrep when present. |
| `Bash` | Execute a shell command. | `{ command: string, timeout_ms?: number }` | **Allowlist only**: `git`, `ls`, `cat`, `grep`, `rg`, `find`, `wc`, `head`, `tail`, `sort`, `uniq`, `diff`. `cwd` locked to notebook root. No pipes-to-network. No `sudo`. Default timeout 30s, max 120s. Stderr captured. |
| `WebFetch` | Fetch a URL and return cleaned text. | `{ url: string, prompt?: string }` | **Gated**: only allowed during the `ingest` op when the URL was the user-supplied source. All other ops: tool not available. Result size capped at 1 MB. |
| `NotebookList` | Custom tool: list notebooks in the library. | `{ }` | Read-only. Returns `{ notebooks: { id: string; name: string; path: string }[] }`. Cross-notebook scope (the only tool that reaches outside the active notebook) — used by Ask to disambiguate "which notebook". |
| `ArticleResolve` | Custom tool: resolve a `[[wikilink]]` to a wiki path. | `{ link: string, from?: string }` | Read-only. Returns `{ resolved: boolean, path?: string, candidates?: string[] }`. Honors aliases and case-insensitive matching. |
| `BacklinkSearch` | Custom tool: list articles linking to a wiki page. | `{ wiki_path: string }` | Read-only. Returns `{ backlinks: { from: string; anchor?: string; line: number }[] }`. |

The lint subagent (Haiku) gets a strict subset: `Read`, `Glob`, `Grep`, `BacklinkSearch`. No write tools. No Bash. No WebFetch. This is enforced by passing a smaller `allowed_tools` list to the Agent SDK.

Tool-call events surface in the SSE `agent.tool_call` event with `tool` set to one of the names above. The `input` field on the event is the same JSON shape as the input schema in this table (truncated to 2 KB for display). The `agent.tool_result` event includes a `summary` field that is the first 500 chars of the tool's stringified result.

### Bash allowlist enforcement

The Bash tool wrapper parses the command with `shlex.split`, rejects any command whose first token is not in the allowlist, rejects any redirection to absolute paths, and rejects any pipeline (`|`, `&&`, `||`, `;`) that includes a non-allowlisted command. Network-capable tools (`curl`, `wget`, `nc`, `ssh`) are not on the allowlist. Examples:

```bash
# allowed:
git log --oneline -n 20
ls wiki/ml
grep -rn "transformer" wiki/
rg --files-with-matches "attention" wiki/
find wiki -name "*.md" -newer wiki/log.md

# rejected:
curl https://example.com               # curl not allowlisted
ls wiki && curl example.com            # pipeline contains non-allowlisted
git push origin main                   # `push` is git but escapes the notebook
sudo git log                           # sudo not allowlisted
ls > /tmp/out                          # redirect to absolute path
```

`git push`, `git pull`, and `git fetch` are syntactically allowed (the first token is `git`) but the wrapper additionally checks for these subcommands and rejects them — sync is the user's responsibility, not the agent's.

### Custom tool result shapes

```ts
type NotebookListResult = { notebooks: { id: string; name: string; path: string }[] };
type ArticleResolveResult = { resolved: boolean; path?: string; candidates?: string[] };
type BacklinkSearchResult = { backlinks: { from: string; anchor?: string; line: number }[] };
```

## FileWatcher events

The watcher is `watchfiles`-based and runs one watcher task per notebook. It emits typed Python events on an in-process asyncio queue and also fans them out as SSE `file.changed` events. Debounce window is **500 ms** — multiple raw OS events coalesce per file path. The watcher ignores everything under `.git/**`, `.notebookai/**`, and `.DS_Store` to avoid feedback loops with itself and with index writes.

| Event | Payload | When emitted |
|---|---|---|
| `raw.added` | `{ notebook_id, path, size, hash }` | New file under `raw/**` after debounce settles. |
| `raw.modified` | `{ notebook_id, path, size, hash }` | Existing `raw/**` file content changes. Should be rare; warns in log. |
| `raw.deleted` | `{ notebook_id, path }` | A `raw/**` file disappears. Triggers cascade-orphan-check active op. |
| `wiki.added` | `{ notebook_id, path, hash }` | New `wiki/**/*.md`. Triggers embedding rebuild for that page. |
| `wiki.modified` | `{ notebook_id, path, hash }` | `wiki/**/*.md` content changes. Triggers re-embed + backlink-graph rebuild for that page. |
| `wiki.deleted` | `{ notebook_id, path }` | `wiki/**/*.md` removed. Triggers backlink-orphan check + removes embedding rows. |
| `chats.added` | `{ notebook_id, path }` | New `chats/**/*.md`. Triggers FTS reindex for the chat. |
| `chats.modified` | `{ notebook_id, path }` | Chat file edited (rare; only via Ask append or human edit). |
| `index.dirty` | `{ notebook_id, scope: "embeddings"\|"fts"\|"backlinks"\|"all", paths: string[] }` | Debounced rollup event. Fires 500 ms after the last raw watcher hit when any of {embeddings, FTS, backlinks} need a rebuild. Consumed by the index-rebuild worker. |

Rebuild semantics: `index.dirty.scope = "embeddings"` triggers **incremental** rebuild — only `paths` are re-embedded; existing rows for those paths are upserted. `scope = "fts"` is also incremental (`UPDATE … WHERE path = ?`). `scope = "backlinks"` rebuilds the in-memory backlink graph for the affected pages plus their immediate neighbors (1-hop). `scope = "all"` is the **full** rebuild path used at startup or after a user-triggered "Rebuild index" action; this drops and re-inserts every embedding/fts row and rebuilds the full backlink graph.

The watcher does not call the LLM. It only mutates `.notebookai/embeddings.db` and `.notebookai/index.db`. Active ops (compile, cascade, etc.) are dispatched only by the API or by the scheduled lint cron — never by the watcher itself.

## GitCommit conventions

Every agent operation produces exactly one commit on `main` (or on the user's branch if they are checked out elsewhere — but the agent is configured to always check out `main` before running an op). Commits use the GPG-signing setting of the user's existing git config; NotebookAI never alters git config.

### Message template

```
[<op>] <short-summary>

<body — bulleted list of files changed and one-line per-file rationale>

notebook-id: <id>
op-id: <ulid>
agent-model: <model-name>
```

`<op>` is one of: `ingest`, `compile`, `cascade`, `archive`, `lint-fix`, `human-edit`. `<short-summary>` is ≤72 chars and describes the user-visible result (e.g. `[compile] add wiki/ml/transformers.md from attention-is-all-you-need.pdf`).

### Operations

- `ingest` — wrote a new `raw/**` file. Body lists the source URL/filename. Always followed by a separate `compile` commit.
- `compile` — wrote/edited `wiki/**` files based on one or more `raw/**` files. Body cites which raw sources were merged.
- `cascade` — propagated a wiki edit to dependent pages (backlink updates, cross-reference rewrites). Triggered after a `compile` if the agent decides cascading is needed; one cascade = one commit.
- `archive` — moved a chat answer or a wiki page into a new wiki article (the "Archive" button in Ask mode). Body cites the source chat.
- `lint-fix` — applied an accepted lint finding's `suggested_fix`. Body includes the `LintFinding.id`.
- `human-edit` — produced by the API endpoints `PUT /api/.../articles/{path}` and direct filesystem edits picked up by the watcher. Author identity is git's normal user (not `notebookai-agent`).

### Authorship

The agent commits with `Author: NotebookAI Agent <agent@notebookai.local>` and `Committer: <git config user>`. Human edits use the git config user for both. The `agent.done` SSE event always includes `commit_sha` for agent ops; for human edits, the `commit.created` SSE event is fired by the watcher.

### Branching

Default: `main`-only. The agent never creates branches for ordinary ops. Optional: per-notebook config flag `agent.lint_branch = true` puts every `lint-fix` op on a `lint/<finding_id>` branch instead of `main`, for users who want to review lint changes via PR-style workflows. Branches merge fast-forward only; conflicts (rare, only on rapid lint+human edits) abort the merge and surface the conflict as a `lint.finding` with `kind: "stale_link"` for the user to resolve.

### Conflict handling

The agent never runs `git merge` with strategies other than fast-forward. If a fast-forward merge fails, the agent aborts the op, leaves the working tree clean (`git stash` + `git stash drop`), emits an `agent.error` SSE event with `retriable: true`, and writes a `LintFinding` describing the conflicting paths so the user can resolve in their editor of choice. The watcher then picks up the human resolution as a `human-edit` commit and the agent retries the op on the next user request.

### Examples

A typical sequence for "ingest one URL" produces two commits in this order:

```
$ git log --oneline
b3a91e2 [compile] add wiki/ml/transformers.md from attention-is-all-you-need.pdf
a18d7c0 [ingest] save raw/ml/2026-05-06-attention-is-all-you-need.md from arxiv.org/abs/1706.03762
```

The body of the `compile` commit:

```
[compile] add wiki/ml/transformers.md from attention-is-all-you-need.pdf

- wiki/ml/transformers.md: new article synthesizing the multi-head attention section
- wiki/index.md: add ML > Transformers entry
- wiki/log.md: append "2026-05-06: compiled transformers.md from raw/ml/2026-05-06-attention-is-all-you-need.md"

notebook-id: ml-research
op-id: 01HW3K7YQF3Z9XS0M2N6P8R4VB
agent-model: claude-sonnet-4-6
```

A `human-edit` commit produced when the user edits an article in the GUI:

```
[human-edit] update wiki/ml/transformers.md

- wiki/ml/transformers.md: clarified positional-encoding section

notebook-id: ml-research
op-id: 01HW3K8AQF3Z9XS0M2N6P8R4VC
```

### Disabled-git mode

When `notebook.json.git_enabled = false`, the same op flow runs but instead of writing a commit, the agent appends one JSON line to `.notebookai/oplog.jsonl`:

```jsonc
{
  "id": "01HW3K7YQF3Z9XS0M2N6P8R4VB",
  "op": "compile",
  "summary": "add wiki/ml/transformers.md from attention-is-all-you-need.pdf",
  "files_changed": ["wiki/ml/transformers.md", "wiki/index.md", "wiki/log.md"],
  "author": "agent",
  "agent_model": "claude-sonnet-4-6",
  "created_at": "2026-05-06T14:25:11Z"
}
```

The `OpLogEntry` shape returned by `GET /api/notebooks/{id}/log` is identical in both modes; the backend abstracts over `git log` vs. `oplog.jsonl` reads.
