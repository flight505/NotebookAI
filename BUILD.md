# BUILD.md — NotebookAI multi-phase build orchestration

> Adapted from the `Bootstrap/BOOTSTRAP.md` pattern (`/Users/jesper/Projects/Dev_projects/Claude_SDK/claude-toolkit/Bootstrap/`).
> The Bootstrap installer is *self-deleting*; this file is *self-archiving* — it survives as the project's build provenance after Phase 14.

**Goal:** Reach `BUILD-COMPLETE` cleanly. Each phase runs as an **isolated subagent** with its own context window, strict contract, and a verification gate that must pass before the next phase starts. The orchestrator (main Claude session) never does the work — it dispatches, verifies, and advances state.

**Version:** 0.1.0
**Source of truth:** This file. Phase tests and helpers are extracted from here on every run; on-disk copies are overwritten.

---

## Prime Directives

Non-negotiable. A violation aborts the build.

1. **One phase at a time.** Phase N's DO steps may not start while Phase N−1's CHECKPOINT is unapproved. No skipping on user request — cumulative tests require ordered execution.
2. **Subagent isolation is the contract.** Each phase is dispatched to a fresh subagent (Agent tool) with: the phase's contract section, the named input artifacts, and nothing else. The orchestrator never lets the subagent see this whole file or sibling phases.
3. **Verify before advancing.** The orchestrator runs `./.notebookai-build/tests/phase-N.sh` after the subagent reports done, shows full stdout + exit code in chat, and only advances on exit 0. "Subagent said it's done" is not a gate.
4. **Cumulative gates.** Phase N's test re-runs Phase 0..N−1 tests as preconditions. A regression in any earlier phase halts the build.
5. **Never modify a passed test to make a later phase pass.** Tests are re-extracted from this file on every run; tampering is overwritten. Fix the artifact under test, not the test.
6. **Never advance past a CHECKPOINT without explicit user approval.** Each phase ends with a checkpoint summary and a wait. The user types "go", "proceed", "next", or equivalent. Silence is not consent.
7. **Working tree mutations are scoped.** Phase outputs go to declared paths only. Off-contract edits to other files are a contract violation. The `.notebookai-build/` directory is the orchestrator's scratch space — never the subagent's.
8. **Source-reference directories are read-only.** `OpenNotebookLM-master/` and `karpathy-llm-wiki-main/` may be read for porting reference. They may not be modified or deleted before Phase 14.
9. **Halt means: stop, surface, do not advance.** Whenever a directive says "halt", the action is identical: print diagnosis to chat, set `phases.<N>.status: "halted"` in state, and stop. The user decides whether to fix-and-resume or abort.
10. **If a phase test fails 3 times in a session, halt.** Surface the failing assertion and the actual artifact state. Do not advance.
11. **If `BUILD.md` is modified during the build, halt.** Phase 0 records its sha256; later phase tests verify via `assert_build_md_unchanged`. A mismatch means the canonical source changed mid-flow.
12. **Never invent contract details.** If a subagent prompt is ambiguous, the orchestrator asks the user (AskUserQuestion). The subagent must not pattern-match to defaults.
13. **Subagent return discipline.** A subagent's final message is a structured report (see "Subagent Return Schema"). The orchestrator parses it and writes a phase entry to state. Free-form returns are a contract violation.
14. **No ad-hoc commits during phases.** Each phase that writes to the working tree commits exactly once at the end of its DO sequence with a phase-named subject. Inter-phase commits must not be amended or rebased.

---

## How It Works

### The mechanism

This file is a long-lived build orchestrator. The orchestrator (main Claude session) walks 15 phases (0–14) in order. Each phase has:

- **Inputs** — files/state on disk required to start.
- **Outputs** — files/state on disk required to pass.
- **THINK** — reasoning the orchestrator writes to chat *before* dispatching.
- **DISPATCH** — the subagent invocation: which agent type, what prompt, what inputs.
- **VERIFY** — `phase-N.sh` script; cumulative; shown verbatim.
- **CHECKPOINT** — user-visible summary; wait for approval.

The orchestrator never writes code itself for phases 1+. It dispatches a subagent. The subagent has its own context window — it can read/write any file the contract specifies but cannot see this file.

### Subagent isolation model

When dispatching a phase, the orchestrator constructs a self-contained prompt:

```
You are running Phase N of NotebookAI's build. Your contract is:

INPUTS: <enumerate files the subagent must read>
OUTPUTS: <enumerate files the subagent must write>
TASK: <natural language description from this file's "DISPATCH" section>
SUCCESS CRITERION: <quote phase-N.sh's headline assertion>
SCOPE LIMITS: <list of paths the subagent must NOT touch>

When done, return a structured report (see Subagent Return Schema).
```

The subagent does not receive: this BUILD.md, future phase contracts, sibling phase outputs unless explicitly listed in INPUTS, or open-ended access to "the project."

### Subagent return schema

Every subagent returns a final message in this exact form:

```
## PHASE-<N>-REPORT
status: pass | fail | partial
files_written: ["path1", "path2", ...]
files_modified: ["path1", ...]
files_unexpected: []        # MUST be empty; non-empty = contract violation
notes: "<2-5 sentences on what was done and any judgment calls>"
verify_hint: "<command the orchestrator should run to verify>"
```

Anything else is a contract violation; the orchestrator halts.

### State

`.notebookai-build/state.json` tracks progress across the build. Schema:

```
{
  "version": "0.1.0",
  "started_at": "2026-05-06T14:23:00Z",
  "current_phase": 0,
  "phases": {
    "0": {"status": "pass", "cookie": "PHASE-0-OK-7f3a9c12", "completed_at": "...", "subagent_id": null, "files": [...]}
  },
  "checksums": {
    "BUILD.md": "sha256:..."
  },
  "decisions": {
    "desktop_shell": "tauri2",
    "conversations_storage": "markdown_canonical",
    "agent_mode": "hybrid_ondemand_with_haiku_lint",
    "library_pattern": "scan_root",
    "sync_recommendation": "git_first"
  }
}
```

### Anti-tamper guarantees

- Phase tests and helpers are re-extracted from `BUILD.md` by `extract.sh` on every orchestrator entry. Local edits to extracted scripts are overwritten.
- `BUILD.md` sha256 is recorded in Phase 0 and verified by every later phase test (`assert_build_md_unchanged`).
- The cumulative-test design means a regression in any earlier phase halts before the new phase runs.

### Resume semantics

If interrupted, the user re-invokes the orchestrator: "resume the NotebookAI build." Phase 0 always re-runs (it's cheap). Completed phases' tests re-run as cumulative preconditions for the next pending phase. State is the source of truth for "what's done"; tests are the source of truth for "is what's done still valid."

---

## Decisions (locked at Phase 1)

The five+one architectural calls from `VISION.md`:

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Desktop shell | **Tauri 2** | ~10 MB bundles, native webviews, OS polish. Spike in Phase 12 if React 19 + Tailwind 4 friction. |
| 2 | Conversations storage | **Markdown canonical, SQLite derived** | Files-all-the-way-down; external-CLI greppable. |
| 3 | Agent operation mode | **On-demand active ops + scheduled Haiku lint + local passive watcher** | Magic without runaway cost; visible budget cap. |
| 4 | Notebook discovery | **Library pattern (scan ~/NotebookAI/notebooks/)** | Matches Obsidian/VSCode mental model; supports external notebook registration. |
| 5 | Sync story | **Git first-class, iCloud/Dropbox/Syncthing as fallback** | Every agent op = one commit; operation log = `git log` rendered. |
| 6 | Embedding scope | **Wiki pages first, raw chunks second** | Aligns retrieval with the substrate; ~10× smaller index. |

Phase 1 emits these into `docs/CONTRACTS.md` as the binding spec.

---

## Phase 0 — Preflight & repo skeleton

### Inputs
- This `BUILD.md` at `/Users/jesper/Projects/NotebookAI/`.
- Source-reference dirs: `OpenNotebookLM-master/`, `karpathy-llm-wiki-main/`.
- (optional) `.notebookai-build/state.json` from a prior interrupted run.

### Outputs
- `.notebookai-build/extract.sh` — phase-script extractor.
- `.notebookai-build/test-helpers.sh` — assertion functions.
- `.notebookai-build/tests/phase-0.sh` … `phase-14.sh` — phase test scripts.
- `.notebookai-build/state.json` — initialized, with `BUILD.md` sha256 recorded.
- Top-level repo skeleton (empty dirs with `.gitkeep`):
  - `backend/`, `frontend/`, `desktop/`, `skills/`, `docs/`, `scripts/`
- `.gitignore` with build/runtime exclusions.
- `README.md` — minimal landing (project name, status: "in build", link to VISION.md).
- Git repo initialized (if not already), first commit: `chore: phase 0 — repo skeleton`.

### THINK (orchestrator writes to chat before acting)
- Are required tools present? (`git`, `python3 ≥ 3.10`, `node ≥ 18`, `pnpm`, `jq`, `bash ≥ 4`, `sha256sum` or `shasum`).
- Is this fresh or resume? Check `.notebookai-build/state.json`.
- Is git repo initialized? `git rev-parse --is-inside-work-tree`.
- Is working tree clean? If not, halt and ask user.
- What is the sha256 of `BUILD.md`? Record it.

### DISPATCH
Phase 0 is the only phase the orchestrator runs **directly** (no subagent). It is environment setup; subagents come from Phase 1 onwards. Steps:

1. Bootstrap the extractor: extract `extract.sh` from this file via awk.
2. Run extract.sh to populate `.notebookai-build/tests/` and `.notebookai-build/`.
3. Detect or initialize git repo. Add `.gitignore`.
4. Create top-level skeleton dirs.
5. Compute sha256 of `BUILD.md`; initialize `state.json`.
6. First commit.

### VERIFY
Run `./.notebookai-build/tests/phase-0.sh`. Show output verbatim. Test asserts:
- All required tools present.
- `BUILD.md` exists and sha256 matches state.
- Skeleton dirs exist.
- `state.json` parses; `current_phase == 0`; `phases.0.status == "pass"`.
- Working tree clean post-commit.
- Cookie `PHASE-0-OK-<sha-prefix>` printed; exit 0.

### CHECKPOINT
Print: tool versions, sha256 prefix, files created (count + paths), git commit hash, cookie. Wait for "go".

---

## Phase 1 — Spec lock-in (CONTRACTS.md)

### Inputs
- Phase 0 complete.
- `VISION.md`.

### Outputs
- `docs/CONTRACTS.md` — locked spec with: 6 architectural decisions (table from above), 7 stable interfaces (Notebook directory schema, REST endpoints, SSE event types, SubagentReport, AgentTool inventory, FileWatcher events, GitCommit conventions).
- `state.json.decisions` populated.
- `phases.1: {status: "pass", cookie}`.
- One commit: `chore: phase 1 — contracts locked`.

### THINK
- Does VISION.md unambiguously answer all 6 decisions? Yes — see the locked table above.
- Are interface signatures stable across phases? List each interface and its consumers.

### DISPATCH (subagent: general-purpose)
Prompt template:

> You are running Phase 1 of NotebookAI's build. Read `VISION.md` and produce `docs/CONTRACTS.md` containing:
>
> **Section 1: Decisions Table** — copy verbatim from BUILD.md's Decisions section.
> **Section 2: Notebook Directory Schema** — exact tree under `~/NotebookAI/notebooks/<id>/`, with field-level spec for `.notebookai/notebook.json`.
> **Section 3: REST API surface** — endpoint list with request/response shapes (no implementations).
> **Section 4: SSE event types** — typed events the agent stream emits.
> **Section 5: Subagent Return Schema** — quote BUILD.md.
> **Section 6: AgentTool inventory** — list of tools the wiki agent has (Read, Write, Edit, Bash with restrictions, etc.).
> **Section 7: FileWatcher events** — what the watcher emits when files in raw/ or wiki/ change.
> **Section 8: GitCommit conventions** — how agent operations map to commit messages.
>
> Each section ≥ 100 chars body. No `<TODO>`, no `lorem ipsum`. Return PHASE-1-REPORT in the schema specified.
>
> SCOPE LIMITS: write only `docs/CONTRACTS.md`. Do not touch other files.

### VERIFY
`./.notebookai-build/tests/phase-1.sh`. Asserts: file exists, all 8 sections present (`## ` headers exact), each ≥ 100 chars body, no forbidden tokens, decisions table matches state. Cookie + exit 0.

### CHECKPOINT
Print: section line counts, key interface excerpts. Wait for "go".

---

## Phase 2 — Skill bundle

### Inputs
- Phase 1.
- `karpathy-llm-wiki-main/SKILL.md` and `karpathy-llm-wiki-main/references/`.

### Outputs
- `skills/karpathy-llm-wiki/SKILL.md` — verbatim copy with frontmatter validated.
- `skills/karpathy-llm-wiki/references/{raw,article,index,archive}-template.md` — copies.
- `skills/karpathy-llm-wiki/README.md` — one-page "what this skill is", citing the Karpathy gist.
- `phases.2: {status, cookie}`.
- Commit: `chore: phase 2 — skill bundle`.

### DISPATCH (subagent: general-purpose)
Copy the four template files and SKILL.md verbatim into `skills/karpathy-llm-wiki/`. Validate SKILL.md frontmatter has `name:` and `description:`. Write a brief README.md.

### VERIFY
`phase-2.sh`: 5 files present, SKILL.md frontmatter parses, no diff between source and copy except whitespace. Cookie + exit 0.

### CHECKPOINT
Print file count, sizes, frontmatter excerpt. Wait.

---

## Phase 3 — Notebook scaffold module

### Inputs
- Phase 2.
- `docs/CONTRACTS.md` § Notebook Directory Schema.

### Outputs
- `backend/pyproject.toml` — Python 3.10+, pytest, ruff, structlog, watchfiles, sqlalchemy 2, pydantic 2.
- `backend/notebookai/__init__.py`.
- `backend/notebookai/scaffold.py` — `create_notebook(root: Path, name: str, *, register_skill_paths: list[str] = ["claude", "agents"]) -> NotebookHandle`. Creates the full directory tree per CONTRACTS.md. Symlinks (or copies) the skill bundle into `.claude/skills/karpathy-llm-wiki/` and `.agents/skills/karpathy-llm-wiki/`.
- `backend/notebookai/cli.py` — `notebookai new <name>` thin CLI.
- `backend/tests/test_scaffold.py` — round-trip tests.
- `phases.3: {status, cookie}`.
- Commit: `feat: phase 3 — notebook scaffold module`.

### DISPATCH (subagent: general-purpose)
Implement scaffold + CLI per CONTRACTS.md schema. Tests must verify: every required file/dir exists, `notebook.json` is valid, skill paths resolve. Use `uv` for the Python env (per global config).

### VERIFY
`phase-3.sh`: `cd backend && uv run pytest tests/test_scaffold.py -q` exits 0. Scaffold a temp notebook and assert tree matches CONTRACTS spec. Cookie + exit 0.

### CHECKPOINT
Print test count + pass count, sample scaffolded tree. Wait.

---

## Phase 4 — Derived index + file watcher

### Inputs
- Phase 3.

### Outputs
- `backend/notebookai/index/schema.py` — SQLAlchemy models for derived index (notebook_meta, source_file, embedding_chunk).
- `backend/notebookai/index/store.py` — sqlite + sqlite-vec wrapper.
- `backend/notebookai/index/embeddings.py` — `bge-small-en-v1.5` via sentence-transformers, with the wiki-pages-first/raw-second strategy from CONTRACTS § Decisions row 6.
- `backend/notebookai/index/watcher.py` — `watchfiles` async loop; emits typed events (CONTRACTS § FileWatcher).
- `backend/notebookai/index/builder.py` — on-event handler that reads file → embeds → upserts.
- `backend/tests/test_index.py` — write a markdown file → assert embedding row appears; delete → assert purge.
- `phases.4: {status, cookie}`.
- Commit: `feat: phase 4 — derived index and watcher`.

### DISPATCH (subagent: general-purpose)
Implement index + watcher with tests. Embedding model is local; fail closed if not available, with a clear error message.

### VERIFY
`phase-4.sh`: pytest passes; smoke script writes `wiki/test/foo.md`, waits, asserts `SELECT count(*) FROM embedding_chunk WHERE source_path LIKE '%foo.md'` > 0. Cookie + exit 0.

### CHECKPOINT
Print test count, embedding model load time, smoke result. Wait.

---

## Phase 5 — Source adapters (port)

### Inputs
- Phase 4.
- `OpenNotebookLM-master/backend/app/adapters/{pdf,url,youtube}.py` (read-only reference).

### Outputs
- `backend/notebookai/adapters/{pdf,url,youtube,base}.py` — repackaged with notebook-aware paths. Each adapter exposes `fetch(source) -> RawDocument` returning markdown + metadata to be written to `raw/<topic>/`.
- `backend/notebookai/adapters/topic.py` — heuristic topic-folder picker (look at existing `raw/` subdirs first).
- `backend/tests/test_adapters.py` — golden-file tests for each adapter (use small fixtures, no network).
- `phases.5: {status, cookie}`.
- Commit: `feat: phase 5 — source adapters`.

### DISPATCH (subagent: general-purpose)
Port the three adapters from OpenNotebookLM-master. Repackage to write into a notebook's `raw/<topic>/` directory. Network calls are isolated and mockable.

### VERIFY
`phase-5.sh`: adapter tests pass; integration test ingests a fixture URL → asserts a markdown file appears under `raw/`. Cookie + exit 0.

### CHECKPOINT
Print adapter list + line counts. Wait.

---

## Phase 6 — Wiki agent (Claude Agent SDK)

### Inputs
- Phases 2, 3, 4, 5.

### Outputs
- `backend/notebookai/agent/runtime.py` — wraps Claude Agent SDK; per-notebook session manager; loads `skills/karpathy-llm-wiki/`.
- `backend/notebookai/agent/tools.py` — exposes Read/Write/Edit/Bash (scoped to the notebook root + skill dir) to the agent.
- `backend/notebookai/agent/operations.py` — high-level entry points: `ingest(notebook, source_url) -> Report`, `query(notebook, prompt) -> Answer`, `lint(notebook, mode='light'|'full') -> Findings`.
- `backend/notebookai/agent/events.py` — typed events emitted on the agent stream (matches CONTRACTS § SSE).
- `backend/tests/test_agent_smoke.py` — boots an agent, asks "list files in wiki/", asserts non-empty response. (Marked `@pytest.mark.requires_claude` — skipped if no OAuth/key.)
- `phases.6: {status, cookie}`.
- Commit: `feat: phase 6 — wiki agent runtime`.

### DISPATCH (subagent: claude-code-guide for Agent SDK reference; then general-purpose for implementation)
Implement the agent runtime. Use Claude Agent SDK (Anthropic). Authenticate via Claude Max OAuth (per global CLAUDE.md — no API key needed for personal use). Agent's tool surface is scoped to the notebook directory + skill bundle — refuse to read/write outside.

### VERIFY
`phase-6.sh`: smoke test passes if Claude is reachable; otherwise prints `SKIP: claude credentials not detected` and exits 0 with a `DEGRADED-PHASE-6-OK` cookie that requires user acknowledgement at checkpoint. Cookie + exit 0.

### CHECKPOINT
Print: agent tool inventory, smoke result. Wait. **This phase requires Claude — confirm credentials with user.**

---

## Phase 7 — FastAPI surface + SSE

### Inputs
- Phase 6.

### Outputs
- `backend/notebookai/api/app.py` — FastAPI app factory.
- `backend/notebookai/api/routers/{notebooks,ingest,ask,lint,articles,log,events}.py` — endpoints per CONTRACTS § REST API.
- `backend/notebookai/api/sse.py` — SSE response helper for agent event stream.
- `backend/notebookai/api/main.py` — uvicorn entry point.
- `backend/tests/test_api.py` — TestClient-driven integration tests.
- `phases.7: {status, cookie}`.
- Commit: `feat: phase 7 — REST API and SSE`.

### DISPATCH (subagent: general-purpose)
Implement the routers + SSE per CONTRACTS. Wire to agent operations from Phase 6. Tests use FastAPI TestClient + tmp notebook root.

### VERIFY
`phase-7.sh`: pytest passes; live curl smoke against `uvicorn` running on a free port: `POST /api/notebooks` creates a notebook, `GET /api/notebooks/{id}/articles` returns []. Cookie + exit 0.

### CHECKPOINT
Print endpoint list, smoke results. Wait.

---

## Phase 8 — Frontend shell + Read mode

### Inputs
- Phase 7.

### Outputs
- `frontend/package.json` — Next.js 15.4, React 19, Tailwind 4, Zustand 5, framer-motion 12, react-markdown, remark-gfm.
- `frontend/app/layout.tsx`, `frontend/app/page.tsx` — three-mode shell with notebook switcher.
- `frontend/app/(modes)/read/page.tsx` — Read mode: tree view + markdown reader + backlinks panel + simple graph view.
- `frontend/lib/api.ts` — typed client for the FastAPI surface.
- `frontend/store/useNotebook.ts` — Zustand store.
- `frontend/components/{NotebookSwitcher,ArticleTree,ArticleReader,Backlinks,GraphView}.tsx`.
- `phases.8: {status, cookie}`.
- Commit: `feat: phase 8 — frontend shell + Read mode`.

### DISPATCH (subagent: general-purpose, possibly with vercel:nextjs / vercel:shadcn for guidance)
Build the Read mode end-to-end: open notebook → see article tree → click article → render markdown with backlinks. Use `pnpm`. Tailwind v4 with `@tailwindcss/postcss`.

### VERIFY
`phase-8.sh`: `pnpm build` exits 0; Playwright smoke (or simpler: curl `pnpm dev` + assert HTML contains "NotebookAI"). Cookie + exit 0.

### CHECKPOINT
Print build size, route list, smoke result. Wait.

---

## Phase 9 — Ask mode

### Inputs
- Phase 8.

### Outputs
- `frontend/app/(modes)/ask/page.tsx` — chat UI with streaming, citation chips that link into Read mode.
- `frontend/components/{ChatTranscript,CitationChip,StreamingText}.tsx`.
- Backend: `backend/notebookai/api/routers/ask.py` returns SSE for streaming answers, conversations persisted as `chats/<date>-<slug>.md`.
- `phases.9: {status, cookie}`.
- Commit: `feat: phase 9 — Ask mode`.

### DISPATCH (subagent: general-purpose)
Implement Ask mode. Conversations save to markdown per CONTRACTS § Decisions row 2.

### VERIFY
`phase-9.sh`: integration test sends `POST /api/notebooks/{id}/ask`, receives SSE chunks, asserts a `chats/*.md` file is written. Frontend builds. Cookie + exit 0.

### CHECKPOINT
Print sample chat markdown, streaming smoke. Wait.

---

## Phase 10 — Curate mode + scheduled lint

### Inputs
- Phase 9.

### Outputs
- `frontend/app/(modes)/curate/page.tsx` — live agent activity feed, lint findings queue, accept/reject actions.
- `frontend/components/{ActivityStream,FindingCard,LintLog}.tsx`.
- Backend: `backend/notebookai/agent/lint.py` — Haiku-driven scheduled lint with budget cap (per CONTRACTS § Decisions row 3).
- Backend: passive watcher (no LLM) emits free findings: orphan raw, broken links.
- `phases.10: {status, cookie}`.
- Commit: `feat: phase 10 — Curate mode + lint`.

### DISPATCH (subagent: general-purpose)
Implement the live stream UI + lint engine. Token budget visible in settings. Findings are queued for user review; accept = agent writes a fix; reject = annotated and dismissed.

### VERIFY
`phase-10.sh`: trigger a lint run with mocked Haiku; assert SSE events stream; assert findings persisted. Cookie + exit 0.

### CHECKPOINT
Print findings list from a sample run, budget snapshot. Wait.

---

## Phase 11 — Git integration

### Inputs
- Phase 10.

### Outputs
- `backend/notebookai/git/notebook_repo.py` — auto-commit hook for every agent op, with generated message per CONTRACTS § GitCommit conventions.
- `backend/notebookai/api/routers/history.py` — `GET /api/notebooks/{id}/history` returns rendered git log.
- Frontend: `frontend/app/(modes)/curate/history/page.tsx` — operation log timeline.
- `phases.11: {status, cookie}`.
- Commit: `feat: phase 11 — git integration`.

### DISPATCH (subagent: general-purpose)
Wire git auto-commit into agent operations. Notebooks scaffolded going forward have `git init` baked in. `.notebookai/` is gitignored within the notebook.

### VERIFY
`phase-11.sh`: ingest a fixture; assert one commit exists in the test notebook with the expected message format. Cookie + exit 0.

### CHECKPOINT
Print recent commits from sample notebook. Wait.

---

## Phase 12 — Tauri 2 desktop shell

### Inputs
- Phases 8, 9, 10 (frontend stable).

### Outputs
- `desktop/` — Tauri 2 project: `src-tauri/`, `Cargo.toml`, `tauri.conf.json`.
- Tauri config for native window vibrancy on macOS, transparent titlebar.
- Frontend builds to `frontend/.next/` (static export-compatible) — Tauri webview loads it.
- Build artifacts ignored in git; Phase 12 produces a one-off binary on the dev machine for the platform Claude is running on.
- `phases.12: {status, cookie}`.
- Commit: `feat: phase 12 — Tauri desktop shell`.

### DISPATCH (subagent: general-purpose with vercel:nextjs for static-export guidance)
Set up Tauri 2. If React 19 + Tailwind 4 + Tauri 2 webview have friction, document the workaround in `desktop/NOTES.md`. Backend runs as a sidecar process started by Tauri.

### VERIFY
`phase-12.sh`: `cd desktop && pnpm tauri build --debug` exits 0 and produces a binary. Cookie + exit 0.

### CHECKPOINT
Print binary path + size, screenshot if possible. Wait.

---

## Phase 13 — Multi-notebook library + cross-CLI verification

### Inputs
- Phase 12.

### Outputs
- `backend/notebookai/library/scanner.py` — scans `~/NotebookAI/notebooks/`, returns metadata for each notebook.
- `backend/notebookai/api/routers/library.py` — `GET /api/library`.
- Frontend: notebook switcher reads from `/api/library`; "Open external notebook" registers a folder.
- `scripts/verify-cross-cli.sh` — manual verification script: scaffolds a notebook, prints instructions for the user to `cd notebooks/<id> && claude` and ingest something via Claude Code, then checks the GUI's index reflects the change.
- `phases.13: {status, cookie}`.
- Commit: `feat: phase 13 — library + cross-CLI`.

### DISPATCH (subagent: general-purpose)
Implement library scan + UI. Document the cross-CLI flow.

### VERIFY
`phase-13.sh`: library scan returns at least one notebook from a fixture root; UI smoke. Manual cross-CLI step is checkpoint-confirmed (test prints instructions, marks itself as `MANUAL-CONFIRMED-PENDING`). Cookie + exit 0.

### CHECKPOINT
Run the cross-CLI verification with the user. Wait for "go" only after they confirm Claude Code edits propagated to the GUI.

---

## Phase 14 — Polish + audit

### Inputs
- Phase 13.

### Outputs
- `README.md` — full product README with screenshots, install instructions, link to VISION.md and CONTRACTS.md.
- `docs/architecture.md` — diagram + narrative.
- `scripts/audit-notebookai.sh` — health check (every phase test runs cumulatively).
- `.claude/skills/audit-notebookai/SKILL.md` — invokable as `/audit-notebookai`.
- `OpenNotebookLM-master/` and `karpathy-llm-wiki-main/` source-reference dirs may now be archived (move to `archive/` or delete) — user decides at checkpoint.
- `phases.14: {status, cookie}`.
- Commit: `chore: phase 14 — polish + audit + archive sources`.
- Final cookie: `BUILD-COMPLETE-<timestamp>`.

### DISPATCH (subagent: general-purpose)
Write final docs + audit script. Ask user before deleting source-reference dirs.

### VERIFY
`phase-14.sh`: every prior phase test passes cumulatively; README has required sections; audit skill loads. Cookie `BUILD-COMPLETE-<ts>` + exit 0.

### CHECKPOINT
Final summary. Print every milestone. Build is done.

---

## Test Scripts (canonical source)

These blocks are extracted by `extract.sh` to `.notebookai-build/` and `.notebookai-build/tests/`. Markers `<!-- TOOL:name.sh -->`...`<!-- /TOOL -->` and `<!-- TEST:name.sh -->`...`<!-- /TEST -->` delimit each block. Content between markers is verbatim.

<!-- TOOL:extract.sh -->
#!/usr/bin/env bash
# Extracts TOOL and TEST blocks from BUILD.md to .notebookai-build/{,tests/}.
set -euo pipefail

SOURCE="${1:-BUILD.md}"
[[ -f "$SOURCE" ]] || { echo "extract.sh: source not found: $SOURCE" >&2; exit 1; }

mkdir -p .notebookai-build/tests

extract_kind() {
  local kind="$1" outdir="$2"
  local current="" in_block=0 line
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^"<!-- ${kind}:"([^[:space:]]+)" -->"$ ]]; then
      current="${BASH_REMATCH[1]}"
      mkdir -p "$(dirname "$outdir/$current")"
      : > "$outdir/$current"
      in_block=1
    elif [[ "$line" == "<!-- /${kind} -->" ]]; then
      in_block=0
      current=""
    elif (( in_block )); then
      printf '%s\n' "$line" >> "$outdir/$current"
    fi
  done < "$SOURCE"
}

extract_kind "TOOL" ".notebookai-build"
extract_kind "TEST" ".notebookai-build/tests"

find .notebookai-build -maxdepth 2 -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
echo "extract.sh: done"
<!-- /TOOL -->

<!-- TOOL:test-helpers.sh -->
#!/usr/bin/env bash
# Assertion helpers shared by every phase test.
# Usage: source ./.notebookai-build/test-helpers.sh

fail() { echo "FAIL: $*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

sha256_of() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  else
    shasum -a 256 "$f" | awk '{print $1}'
  fi
}

assert_file_exists() { [[ -f "$1" ]] || fail "expected file: $1"; }
assert_dir_exists() { [[ -d "$1" ]] || fail "expected directory: $1"; }

assert_state_phase_pass() {
  local n="$1"
  local status
  status=$(jq -r ".phases.\"$n\".status // \"missing\"" .notebookai-build/state.json)
  [[ "$status" == "pass" ]] || fail "phase $n status: $status"
}

assert_build_md_unchanged() {
  local recorded actual
  recorded=$(jq -r '.checksums."BUILD.md"' .notebookai-build/state.json)
  actual="sha256:$(sha256_of BUILD.md)"
  [[ "$recorded" == "$actual" ]] || fail "BUILD.md sha256 changed since Phase 0 (recorded=$recorded actual=$actual)"
}

run_prior_phase_tests() {
  local upto="$1"
  local i
  for ((i=0; i<upto; i++)); do
    [[ -x ".notebookai-build/tests/phase-$i.sh" ]] || fail "missing prior test: phase-$i.sh"
    bash ".notebookai-build/tests/phase-$i.sh" >/dev/null || fail "prior phase $i regressed"
  done
}

print_cookie() {
  local phase="$1"
  local prefix
  prefix=$(sha256_of BUILD.md | cut -c1-8)
  echo "PHASE-${phase}-OK-${prefix}"
}
<!-- /TOOL -->

<!-- TEST:phase-0.sh -->
#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

require_cmd git
require_cmd jq
require_cmd python3
require_cmd node
require_cmd pnpm

assert_file_exists BUILD.md
assert_file_exists .notebookai-build/state.json
assert_file_exists .notebookai-build/extract.sh
assert_file_exists .notebookai-build/test-helpers.sh

assert_dir_exists backend
assert_dir_exists frontend
assert_dir_exists desktop
assert_dir_exists skills
assert_dir_exists docs
assert_dir_exists scripts

assert_build_md_unchanged
assert_state_phase_pass 0

# Working tree clean post-commit
git diff --quiet || fail "working tree dirty"
git diff --cached --quiet || fail "staged changes present"

print_cookie 0
<!-- /TEST -->

<!-- TEST:phase-1.sh -->
#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 1
assert_file_exists docs/CONTRACTS.md

for h in "Decisions" "Notebook Directory Schema" "REST API surface" "SSE event types" "Subagent Return Schema" "AgentTool inventory" "FileWatcher events" "GitCommit conventions"; do
  grep -qE "^## .*${h}" docs/CONTRACTS.md || fail "CONTRACTS.md missing section: $h"
done

! grep -q "<TODO>" docs/CONTRACTS.md || fail "TODO token in CONTRACTS.md"
! grep -qi "lorem ipsum" docs/CONTRACTS.md || fail "lorem ipsum in CONTRACTS.md"

assert_state_phase_pass 1
print_cookie 1
<!-- /TEST -->

<!-- TEST:phase-2.sh -->
#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 2
assert_file_exists skills/karpathy-llm-wiki/SKILL.md
assert_file_exists skills/karpathy-llm-wiki/references/raw-template.md
assert_file_exists skills/karpathy-llm-wiki/references/article-template.md
assert_file_exists skills/karpathy-llm-wiki/references/index-template.md
assert_file_exists skills/karpathy-llm-wiki/references/archive-template.md
assert_file_exists skills/karpathy-llm-wiki/README.md

grep -qE "^name: " skills/karpathy-llm-wiki/SKILL.md || fail "SKILL.md missing name frontmatter"
grep -qE "^description: " skills/karpathy-llm-wiki/SKILL.md || fail "SKILL.md missing description frontmatter"

assert_state_phase_pass 2
print_cookie 2
<!-- /TEST -->

Tests for Phase 3..14 are stubbed in `.notebookai-build/tests/phase-N.sh.stub` and finalized when their phase begins (cumulative-test discipline allows this — earlier phases stay locked once their tests are in canonical form).

---

## Glossary

- **Orchestrator** — the main Claude session running this BUILD.md.
- **Subagent** — a fresh Agent SDK invocation with its own context window, dispatched per phase.
- **Cookie** — `PHASE-N-OK-<sha-prefix>` token printed by a passing test; recorded in state.
- **Cumulative test** — a phase test that re-runs all prior phase tests as preconditions before its own assertions.
- **Source-reference dirs** — `OpenNotebookLM-master/`, `karpathy-llm-wiki-main/`. Read-only until Phase 14.
- **Notebook root** — a directory containing `.notebookai/notebook.json`. The unit of content.

---

## Resumption

To resume after interruption:

1. The user prompts: "resume the NotebookAI build."
2. Orchestrator re-runs Phase 0 (cheap; verifies env + extracts scripts).
3. Orchestrator runs every passed phase test cumulatively to detect regressions.
4. Orchestrator advances to the lowest pending phase and dispatches its subagent.

This file is the only source of truth. State + tests are derived.
