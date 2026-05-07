"""Demo notebook seeding.

Populates a fresh notebook with a small but coherent corpus the user can
click around on the very first launch — three wiki articles and one chat,
all hand-written (no LLM calls). Designed to exercise the full feature
surface in seconds: wikilinks, backlinks, citations, chats with
frontmatter, and the wiki index/log bookkeeping files.

The demo notebook always has id ``demo-notebook``. Calling
:func:`create_demo_notebook` twice is a no-op the second time — the
existing notebook is returned as-is.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import structlog

from notebookai.library.scanner import LibraryScanner, NotebookEntry
from notebookai.scaffold import create_notebook

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Hand-written content. Keep total under 500 lines.
# ---------------------------------------------------------------------------


_WELCOME_MD = """\
---
title: Welcome
tags: [meta]
raw_refs: []
---

# Welcome

You're inside a NotebookAI **demo notebook** — a tiny, curated corpus
meant to show what a populated knowledge base feels like. Read this
article, then click any of the wiki-style links to bounce around.

NotebookAI is a local-first knowledge workspace. Sources land in
`raw/`, the agent compiles them into `wiki/`, and your conversations
live in `chats/`. The product thesis lives in the repository
`VISION.md`.

## Try this

- Open [[transformers]] — a sample article on a real topic.
- Open [[how-this-wiki-works]] — explains the conventions the agent
  follows when it writes here.
- Switch to **Ask** mode and try a question. With no Claude credentials
  it answers from the local index in wiki-only mode.
- Switch to **Curate** mode to watch the agent's activity stream and
  review lint findings.

When you're done exploring, you can delete this notebook (Library
panel → right-click → Delete) and start your own.
"""


_TRANSFORMERS_MD = """\
---
title: Transformers
tags: [ml, deep-learning]
raw_refs: []
---

# Transformers

The Transformer is a neural network architecture introduced in the 2017
paper "Attention Is All You Need" by Vaswani et al. It replaced the
recurrent and convolutional building blocks of earlier sequence models
with a single primitive: **scaled dot-product attention**, applied many
times in parallel.

## Why it mattered

Before Transformers, sequence models like LSTMs processed tokens one at
a time, which made training slow and made it hard for the model to
relate distant tokens. Attention computes pairwise relevance scores
across the entire sequence in a single matrix multiplication, so every
token can directly attend to every other token. This unlocked massively
parallel training on GPUs and TPUs and turned out to scale far better
than anyone expected.

## Anatomy

A Transformer block stacks two sub-layers: multi-head self-attention,
then a position-wise feed-forward network. Residual connections and
layer normalisation wrap each sub-layer. Stacks of these blocks make up
modern decoder-only language models.

> [^1]: Vaswani et al., 2017 — "we propose a new simple network
>   architecture, the Transformer, based solely on attention mechanisms"

## See also

- [[welcome]] — the demo overview.
- [[how-this-wiki-works]] — the conventions used by this article.
"""


_HOW_THIS_WORKS_MD = """\
---
title: How this wiki works
tags: [meta]
raw_refs: []
---

# How this wiki works

This notebook follows the **karpathy-llm-wiki** convention. Three
subtrees matter:

- `raw/` — immutable source material (PDFs, scraped pages, transcripts).
- `wiki/` — compiled, human-readable markdown maintained by the agent.
- `chats/` — conversations with the agent persisted as markdown with
  frontmatter.

The agent owns `wiki/`. It may *read* `raw/` but never modifies files
there after ingest. Two bookkeeping files at the top of `wiki/` are
always kept up to date:

- `wiki/index.md` — table of contents linking out to every article.
- `wiki/log.md` — append-only log of every operation the agent
  performed.

## Linking

Internal links use the `[[name]]` wikilink syntax. They resolve against
all of `wiki/**`, so `[[transformers]]` finds
`wiki/ml/transformers.md`. Backlinks (the right rail in Read mode) are
computed automatically.

## Citations

Factual claims should cite their wiki source via a numbered footnote:

```
> [^1]: wiki/ml/transformers.md — "the exact phrase that supports the claim"
```

The agent's job is to compose, not to invent — every claim should be
traceable to something in `raw/` or another `wiki/` article.
"""


_WIKI_INDEX_MD = """\
# Knowledge Base Index

Welcome to the demo notebook. This index links to every article in the
wiki. Use it as a launching pad.

## General

- [[welcome]] — start here.
- [[how-this-wiki-works]] — wiki conventions explained.

## ML

- [[transformers]] — the architecture behind modern LLMs.
"""


_WIKI_LOG_MD = """\
# Wiki Log

- 2026-05-07T00:00:00Z — `seed` — scaffolded demo notebook with 3
  articles and 1 sample chat.
"""


_DEMO_CHAT_MD = """\
---
chat_id: "demo-getting-started"
notebook_id: "demo-notebook"
title: "Getting started with NotebookAI"
created_at: "2026-05-07T00:00:00Z"
updated_at: "2026-05-07T00:00:01Z"
model: "demo"
---
## user · 2026-05-07T00:00:00Z

What is this notebook for?

## agent · 2026-05-07T00:00:01Z

This is a demo notebook seeded by NotebookAI to show you what a
populated workspace looks like. It contains three short wiki articles
([[welcome]], [[transformers]], and [[how-this-wiki-works]]) plus this
sample chat. Click the wikilinks to navigate, or open Ask mode to try a
question against this corpus.

> [^1]: wiki/general/welcome.md — "you're inside a NotebookAI demo notebook"
"""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


DEMO_NOTEBOOK_NAME = "Demo Notebook"
DEMO_NOTEBOOK_ID = "demo-notebook"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_demo_notebook(library_root: Path) -> NotebookEntry:
    """Scaffold (or return) the demo notebook under ``library_root``.

    Idempotent: if a notebook with id ``demo-notebook`` already exists,
    return its current :class:`NotebookEntry` without modifying the
    on-disk content.
    """
    library_root = Path(library_root).expanduser()
    library_root.mkdir(parents=True, exist_ok=True)

    scanner = LibraryScanner(library_root)
    existing = scanner.find_by_id(DEMO_NOTEBOOK_ID)
    if existing is not None:
        return existing

    handle = create_notebook(
        library_root,
        DEMO_NOTEBOOK_NAME,
        git_enabled=True,
    )
    root = handle.root

    # Wiki articles. Use the topical layout the karpathy-llm-wiki skill
    # expects: wiki/<topic>/<slug>.md, plus wiki/index.md & wiki/log.md
    # at the top level.
    general_dir = root / "wiki" / "general"
    ml_dir = root / "wiki" / "ml"
    general_dir.mkdir(parents=True, exist_ok=True)
    ml_dir.mkdir(parents=True, exist_ok=True)

    (general_dir / "welcome.md").write_text(_WELCOME_MD, encoding="utf-8")
    (general_dir / "how-this-wiki-works.md").write_text(
        _HOW_THIS_WORKS_MD, encoding="utf-8"
    )
    (ml_dir / "transformers.md").write_text(_TRANSFORMERS_MD, encoding="utf-8")
    (root / "wiki" / "index.md").write_text(_WIKI_INDEX_MD, encoding="utf-8")
    (root / "wiki" / "log.md").write_text(_WIKI_LOG_MD, encoding="utf-8")

    # Sample chat.
    chats_dir = root / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / "2026-05-07-getting-started.md").write_text(
        _DEMO_CHAT_MD, encoding="utf-8"
    )

    # The scaffold defaulted name to "Demo Notebook" already; we touch
    # notebook.json to be explicit and to update the timestamp.
    meta_path = root / ".notebookai" / "notebook.json"
    if meta_path.is_file():
        try:
            import json

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["name"] = DEMO_NOTEBOOK_NAME
            meta_path.write_text(
                json.dumps(meta, indent=2) + "\n", encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            log.warning(
                "demo.notebook_meta_rewrite_failed",
                path=str(meta_path),
                error=str(exc),
            )

    # Commit the seeded content if git is enabled. The scaffold made an
    # initial commit of the empty tree; we add a second commit so the
    # demo content is captured under the "NotebookAI Demo" author.
    if (root / ".git").is_dir():
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=NotebookAI Demo",
                    "-c",
                    "user.email=demo@notebookai.local",
                    "commit",
                    "-q",
                    "-m",
                    "demo: seed welcome content",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            log.warning(
                "demo.git_commit_failed",
                root=str(root),
                error=str(exc),
            )

    log.info(
        "demo.created",
        id=DEMO_NOTEBOOK_ID,
        root=str(root),
        when=datetime.now(timezone.utc).isoformat(),
    )

    entry = scanner.find_by_id(DEMO_NOTEBOOK_ID)
    if entry is None:  # pragma: no cover - we just created it
        raise RuntimeError(
            f"demo notebook created but scanner failed to find id={DEMO_NOTEBOOK_ID}"
        )
    return entry


__all__ = [
    "DEMO_NOTEBOOK_ID",
    "DEMO_NOTEBOOK_NAME",
    "create_demo_notebook",
]
