---
name: audit-notebookai
description: "Run NotebookAI's full audit — phase tests, pytest suite, frontend build, ruff. Use when verifying repo health after a refactor or before release."
---

# audit-notebookai

Use this skill to verify the NotebookAI repo is healthy end-to-end.

## When to use

- After any refactor that touched multiple modules.
- Before tagging a release or merging into `main`.
- When a phase gate test starts failing and you need to know which other phases regressed.
- When CI is unavailable and you need a one-shot local check.

## What it does

Invokes `scripts/audit-notebookai.sh` from the repo root. The script:

1. Runs every phase gate (`.notebookai-build/tests/phase-0.sh` through `phase-13.sh`) in order. Each must emit a `PHASE-N-OK-<sha>` cookie.
2. Runs the backend pytest suite excluding `requires_claude` markers (`cd backend && uv run pytest tests/ -m "not requires_claude"`).
3. Runs the backend `ruff check` lint.
4. Builds the frontend (`cd frontend && pnpm build`).
5. If `cargo` is available, runs `cargo check` against `desktop/src-tauri/`.
6. Prints a summary: phases verified, pytest pass count, total lines of code, and every phase cookie.

Exits 0 on success, non-zero on any failure.

## How to invoke

From the NotebookAI repo root:

```bash
bash scripts/audit-notebookai.sh
```

Surface the full output to the user. The summary at the end is the canonical health signal — every line under `Summary` should be present and the last line should read `NotebookAI audit: PASS`.

## What to do on failure

- A failed phase gate points at exactly which contract regressed; open `.notebookai-build/tests/phase-N.sh` to see the assertion that fired.
- Pytest failures: re-run with `-vv` against the failing file in `backend/tests/`.
- Ruff: most violations have `--fix` autofixes; suggest those before manual edits.
- Frontend build: `cd frontend && pnpm build` for the full Next.js trace.
- `cargo check`: usually a missing dependency in `desktop/src-tauri/Cargo.toml`.
