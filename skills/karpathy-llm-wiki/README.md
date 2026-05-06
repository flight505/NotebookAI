# karpathy-llm-wiki (NotebookAI bundle)

This directory bundles the **Karpathy LLM Wiki** skill for use inside NotebookAI.
The skill provides a structured workflow for building and maintaining a personal,
LLM-curated knowledge base out of two directories: `raw/` (immutable source
material) and `wiki/` (compiled articles).

## Origin

- Original gist by Andrej Karpathy:
  https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Upstream repo (template + skill packaging):
  https://github.com/Astro-Han/karpathy-llm-wiki

The five files in this bundle (`SKILL.md` plus the four templates under
`references/`) are copied verbatim from the upstream snapshot stored at
`karpathy-llm-wiki-main/` in the NotebookAI repo. Do not hand-edit them
here — refresh from upstream if a new version is needed.

## How NotebookAI uses this skill

NotebookAI is a multi-notebook research workspace. Each notebook is its own
isolated workspace under `notebooks/<slug>/` and gets its own `raw/` and
`wiki/` directories.

Per `docs/CONTRACTS.md`, the scaffolding step for a new notebook symlinks this
bundle into both the Claude Code skills path and the agent skills path:

- `notebooks/<slug>/.claude/skills/karpathy-llm-wiki` → `../../../../skills/karpathy-llm-wiki`
- `notebooks/<slug>/.agents/skills/karpathy-llm-wiki`  → `../../../../skills/karpathy-llm-wiki`

The dedicated **wiki agent** (added in Phase 6) loads this skill automatically
and is responsible for keeping each notebook's wiki coherent as new sources
arrive.

## The three operations

1. **Ingest** — Add a new source to `raw/` (PDF, web page, transcript, note),
   normalize it against `references/raw-template.md`, and either create or
   update one or more articles in `wiki/` using `references/article-template.md`.
2. **Query** — Answer a question by reading the wiki first (compiled
   knowledge), falling back to `raw/` only when the wiki is incomplete, and
   citing the underlying raw sources.
3. **Lint** — Audit the wiki for broken links, stale claims, duplicate
   articles, missing index entries (`references/index-template.md`), and
   archive candidates (`references/archive-template.md`).

See `SKILL.md` in this directory for the full operational contract.
