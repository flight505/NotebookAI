# Wiki-only mode

NotebookAI runs in "wiki-only mode" automatically whenever the Claude Agent
SDK has no usable credentials. The product stays usable for everything that
can be done locally; the steps that genuinely require Claude are skipped
with an honest note rather than failing.

## When does it trigger?

The runtime checks two locations and falls back to wiki-only mode if neither
is found:

- `ANTHROPIC_API_KEY` set in the process environment.
- A Claude Code OAuth credential file at one of:
  - `~/.claude/.credentials.json`
  - `~/.config/claude/credentials.json`

The check runs per-request, so adding credentials and reopening the app
flips the UI back to "Claude ready" without restarting the backend.

## What still works

| Feature      | Wiki-only behaviour                                            |
|--------------|----------------------------------------------------------------|
| Ingest       | Adapter writes `raw/<topic>/<slug>.md`. `wiki/index.md` gets a "Pending compilation" entry; `wiki/log.md` records the ingest. **No** wiki article is generated. |
| Ask          | Local vector search returns the top-K wiki chunks; the answer is a citation-prefixed list of those snippets. No synthesis. |
| Lint         | Passive watcher runs (`orphan_raw`, `broken_wikilink`, `broken_path_link`). Findings persist as usual. |
| Read mode    | Unchanged — articles, backlinks, graph view all read from disk. |
| History/Log  | Unchanged — git commits and the oplog are local-only. |

## What does not work

- **Compile** — converting a raw source into a wiki article. The raw file
  still lands in `raw/`, so re-running ingest after enabling Claude will
  pick it up.
- **Cascade-update** — propagating a wiki edit through related articles.
- **Haiku-driven lint** — contradictions, missing cross-refs, thin coverage.
- **Archive** — turning a chat answer into a wiki article.

## Surfacing in the UI

- Top-nav badge: amber "Wiki-only mode" pill (vs. green "Claude ready").
  Tooltip explains the constraint and links here.
- Ask page: an amber banner above the transcript notes that answers are
  retrieved chunks, not synthesis.
- A non-blocking toast appears the first time the SSE
  `agent.unavailable` event fires per session.
- API: `GET /api/notebooks/{id}` includes
  `agent_status: { available, reason }`. Active-op routes also include a
  `degraded: bool` field on their response payload.

## How to enable Claude

Pick one:

1. **API key** — `export ANTHROPIC_API_KEY=sk-ant-...` and restart the
   sidecar. Suitable for development or running unattended.
2. **OAuth (Claude Max)** — install Claude Code and run
   `claude setup-token`. The sidecar picks up the credential file
   automatically.

Once either path is in place, reload the notebook in the UI; the badge
will switch to "Claude ready" and ingest/ask/lint will use the agent
again.
