# NotebookAI

> Local-first, agent-native knowledge workspace. Each notebook is a folder of plain markdown that compounds over time — usable from a polished GUI **and** from any agent CLI (Claude Code, Codex, Antigravity, Cursor) pointed at the same folder.

**Status:** in build. See [BUILD.md](BUILD.md) for the multi-phase build plan and [VISION.md](VISION.md) for the product thesis.

## Build status

| Phase | Title | Status |
|---|---|---|
| 0 | Preflight & repo skeleton | in progress |
| 1 | Spec lock-in (`docs/CONTRACTS.md`) | pending |
| 2 | Skill bundle | pending |
| 3 | Notebook scaffold module | pending |
| 4 | Derived index + file watcher | pending |
| 5 | Source adapters (port) | pending |
| 6 | Wiki agent (Claude Agent SDK) | pending |
| 7 | FastAPI surface + SSE | pending |
| 8 | Frontend shell + Read mode | pending |
| 9 | Ask mode | pending |
| 10 | Curate mode + scheduled lint | pending |
| 11 | Git integration | pending |
| 12 | Tauri 2 desktop shell | pending |
| 13 | Multi-notebook library + cross-CLI verification | pending |
| 14 | Polish + audit | pending |

## How the build works

Each phase runs as an isolated subagent with its own context window, a strict input/output contract, and a verification gate that must pass before the next phase starts. The orchestrator (main Claude session) dispatches, verifies, and advances state — it never does the work directly.

State machine: `.notebookai-build/state.json`. Phase tests: `.notebookai-build/tests/phase-N.sh`. The contracts and tests are extracted from `BUILD.md` on every orchestrator entry; on-disk copies are overwritten.
