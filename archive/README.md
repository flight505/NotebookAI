# archive/

Read-only reference material that informed NotebookAI's design. Preserved here so future contributors can trace the lineage of design decisions, but **not part of the running product** — nothing in this directory is imported by `backend/`, `frontend/`, or `desktop/`.

Moved into `archive/` during Phase 14 (polish + audit) of the build, after the equivalent functionality was reimplemented natively in `backend/notebookai/` and the karpathy-llm-wiki skill was packaged into `skills/karpathy-llm-wiki/` (the canonical scaffold source).

## Contents

### `OpenNotebookLM-master/`

The original NotebookLM-style RAG project that NotebookAI evolved out of. The pieces that survived the migration:

- `app/adapters/{pdf,url,youtube}.py` → reimplemented in `backend/notebookai/adapters/`
- `app/services/embeddings.py` (sentence-transformers wrapper) → reimplemented in `backend/notebookai/index/embeddings.py`
- `app/services/chunking.py` → reimplemented in `backend/notebookai/index/builder.py`
- sqlite-vec wiring → reimplemented in `backend/notebookai/index/store.py`

The pieces that were deliberately discarded (see [VISION.md](../VISION.md) §"Migration from OpenNotebookLM"): JWT auth, multi-user routing, the `Project → Document → Chunk → Conversation → Message` SQLAlchemy hierarchy as primary state, the chat-centric four-pane layout, the cloud-deployable FastAPI surface.

### `karpathy-llm-wiki-main/`

Karpathy's original `llm-wiki` reference implementation. The wiki-as-substrate model (compile / cascade / lint / query / archive ops) is taken directly from this repo. The skill bundle at [`skills/karpathy-llm-wiki/`](../skills/karpathy-llm-wiki/) is the production version — it adapts the original for the agent-skills standard so any skill-aware CLI can use it.

## Don't edit these

These directories are kept verbatim for provenance. If you need to change behavior, change `backend/notebookai/`, `skills/karpathy-llm-wiki/`, or `frontend/` — the live code paths.

If you're trying to delete `archive/` to slim the repo: it's safe. Nothing in the running NotebookAI product depends on it.
