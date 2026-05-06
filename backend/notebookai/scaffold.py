"""Notebook scaffolding.

Creates a notebook directory matching the binding schema in docs/CONTRACTS.md.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models — match docs/CONTRACTS.md § Notebook Directory Schema exactly.
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    """`notebook.json.agent` sub-object."""

    model_config = ConfigDict(extra="allow")

    model: str = "claude-sonnet-4-6"
    lint_model: str = "claude-haiku-4-5-20251001"
    lint_schedule: Literal["hourly", "daily", "off"] = "hourly"
    lint_budget_tokens_per_day: int = Field(default=50000, ge=0)


class EmbeddingsConfig(BaseModel):
    """`notebook.json.embeddings` sub-object."""

    model_config = ConfigDict(extra="allow")

    model: str = "bge-small-en-v1.5"
    dim: int = Field(default=384, ge=1)


class NotebookMeta(BaseModel):
    """Canonical `.notebookai/notebook.json` schema."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    name: str = Field(min_length=1, max_length=120)
    created_at: str  # RFC3339 UTC
    schema_version: int = Field(default=1, ge=1)
    git_enabled: bool = True
    agent: AgentConfig = Field(default_factory=AgentConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    description: str | None = Field(default=None, max_length=512)


# ---------------------------------------------------------------------------
# Handle
# ---------------------------------------------------------------------------


@dataclass
class NotebookHandle:
    """Returned from `create_notebook`. Lightweight — just root + meta."""

    root: Path
    meta: NotebookMeta
    extra: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"<NotebookHandle id={self.meta.id} root={self.root}>"


# ---------------------------------------------------------------------------
# Slugification
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DASH_COLLAPSE_RE = re.compile(r"-{2,}")


def _slugify(name: str) -> str:
    """Lowercase, ASCII, kebab-case. Collapses repeated hyphens."""
    # Normalize unicode → ASCII (drops accents).
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    replaced = _SLUG_RE.sub("-", lowered)
    collapsed = _DASH_COLLAPSE_RE.sub("-", replaced)
    return collapsed.strip("-")


# ---------------------------------------------------------------------------
# Skill bundle resolution
# ---------------------------------------------------------------------------


def _default_skill_bundle() -> Path:
    """Resolve the repo's `skills/karpathy-llm-wiki/` from this file's location.

    scaffold.py → notebookai/ → backend/ → repo root → skills/karpathy-llm-wiki
    """
    return Path(__file__).resolve().parents[2] / "skills" / "karpathy-llm-wiki"


def _link_skill(target: Path, bundle: Path) -> str:
    """Create symlink at `target` pointing to `bundle`. Falls back to copy.

    Returns "symlink" or "copy" indicating the path that resolved.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(bundle, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError) as exc:
        log.warning(
            "scaffold.symlink_failed_falling_back_to_copy",
            target=str(target),
            bundle=str(bundle),
            error=str(exc),
        )
        shutil.copytree(bundle, target)
        return "copy"


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


_GITIGNORE = """\
.notebookai/index.db
.notebookai/embeddings.db
.notebookai/locks/
.DS_Store
"""


def _agents_md(meta: NotebookMeta) -> str:
    return f"""\
# AGENTS.md — {meta.name}

## What this is

This folder is a NotebookAI notebook — a local-first, LLM-maintained knowledge
base. It has four meaningful subtrees:

- `raw/` — immutable source material (PDFs, scraped articles, transcripts).
  Files land here at ingest time and are never modified afterwards.
- `wiki/` — compiled knowledge: human-readable markdown articles maintained by
  the agent. `wiki/index.md` is the top-level table of contents and
  `wiki/log.md` is the operation log. This is the only tree the agent writes
  to.
- `chats/` — conversations with the agent persisted as markdown.
- `.notebookai/` — derived state (SQLite index, embeddings, locks). Safe to
  delete; rebuilds on next watcher tick.

## How to operate it

The full operating contract lives in `.claude/skills/karpathy-llm-wiki/SKILL.md`
(also mirrored at `.agents/skills/karpathy-llm-wiki/SKILL.md`). Read it before
acting. The skill defines three operations:

- **Ingest** — a new file appears under `raw/`; read it, decide whether to
  extend an existing wiki article or create a new one, write to `wiki/`,
  refresh `wiki/index.md`, append a line to `wiki/log.md`.
- **Query** — answer a user question by reading `wiki/index.md`, following
  wikilinks, and citing sources.
- **Lint** — fix broken wikilinks, index drift, missing "See also"
  cross-references; surface heuristic issues for review.

## Conventions

Chat markdown format — chats are markdown files with YAML front-matter and
`## role · ts` section headers per turn:

```
---
chat_id: "01H..."
notebook_id: "{meta.id}"
---
## user · 2026-01-01T12:00:00Z

What's the architecture?

## agent · 2026-01-01T12:00:01Z

It's a local-first ...
```

Citation format — every factual claim quotes its wiki source via a numbered
footnote:

```
> [^1]: wiki/general/example.md — "the exact phrase that supports the claim"
```

Wikilinks — internal references use `[[name]]` (resolved against `wiki/**`).
Front-matter for raw files: `id`, `source_type`, `source_url`, `title`,
`published`, `collected_at`, `topic`. Front-matter for wiki articles: `title`,
`tags`, `raw_refs` (list of `raw/...` paths backing the article).

## Do not edit

The agent must never write or delete:

- `.notebookai/index.db` — derived; rebuilt by the watcher.
- `.notebookai/embeddings.db` — derived; rebuilt by the watcher.
- `.notebookai/locks/` — runtime concurrency control.
- `.git/` — managed by the commit workflow.

The agent owns `wiki/`. It may *read* `raw/` but must never modify, rename, or
delete files there after ingest.

## Budget invariant

The passive watcher (filesystem → index/embeddings) never spends LLM tokens —
it runs on local CPU using sentence-transformers. The scheduled lint pass uses
the cheap Haiku model and is bounded by `agent.lint_budget_tokens_per_day`
(read from `.notebookai/notebook.json`). If a lint run would exceed the daily
budget it stops early and resumes the next scheduled tick.

## Cross-CLI

The same skill is installed at `.claude/skills/karpathy-llm-wiki/` (Claude
Code) and `.agents/skills/karpathy-llm-wiki/` (agentskills.io). Any
SDK-compatible CLI may operate on this folder — the skill, conventions, and
"do not edit" list apply identically.

Notebook id: `{meta.id}`
Created: `{meta.created_at}`
Schema version: `{meta.schema_version}`
"""


def _readme(meta: NotebookMeta) -> str:
    return f"""\
# {meta.name}

<!-- notebookai:auto-start -->

Created: `{meta.created_at}`
Notebook id: `{meta.id}`

This is a NotebookAI notebook. See [`AGENTS.md`](./AGENTS.md) for the operating
contract used by agents that work in this folder.

<!-- notebookai:auto-end -->
"""


_WIKI_INDEX = "# Knowledge Base Index\n\n"
_WIKI_LOG = "# Wiki Log\n\n"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def create_notebook(
    root: Path,
    name: str,
    *,
    register_skill_paths: tuple[str, ...] | list[str] = ("claude", "agents"),
    skill_bundle: Path | None = None,
    git_enabled: bool = True,
    now: Callable[[], datetime] | None = None,
) -> NotebookHandle:
    """Scaffold a new notebook directory under ``root``.

    Args:
        root: The library root (e.g. ``~/NotebookAI/notebooks``). The notebook
            is created at ``root/<id>``.
        name: Human display name. Slugified to derive ``id``.
        register_skill_paths: Surfaces to install the skill under. Default is
            both ``"claude"`` and ``"agents"``.
        skill_bundle: Path to the skill bundle. Defaults to the repo's
            ``skills/karpathy-llm-wiki/``.
        git_enabled: Whether to ``git init`` and create the initial commit.
        now: Optional clock for tests.

    Returns:
        A :class:`NotebookHandle` for the freshly created notebook.

    Raises:
        ValueError: If the slugified name is empty.
        FileExistsError: If the notebook directory already exists.
        FileNotFoundError: If the skill bundle does not contain ``SKILL.md``.
    """
    nb_id = _slugify(name)
    if not nb_id:
        raise ValueError(f"Could not derive a notebook id from name {name!r}")

    nb_path = (root / nb_id).resolve()
    if nb_path.exists():
        raise FileExistsError(nb_path)

    bundle = (skill_bundle or _default_skill_bundle()).resolve()
    if not (bundle / "SKILL.md").is_file():
        raise FileNotFoundError(
            f"skill bundle missing SKILL.md: {bundle}"
        )

    # Build metadata.
    clock = now or (lambda: datetime.now(timezone.utc))
    created_at = clock().strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = NotebookMeta(
        id=nb_id,
        name=name,
        created_at=created_at,
        git_enabled=git_enabled,
    )

    # Create the directory tree.
    nb_path.mkdir(parents=True, exist_ok=False)
    (nb_path / ".notebookai").mkdir()
    (nb_path / ".notebookai" / "locks").mkdir()
    (nb_path / "raw").mkdir()
    (nb_path / "wiki").mkdir()
    (nb_path / "chats").mkdir()

    # Skill surfaces.
    skill_install_modes: dict[str, str] = {}
    for surface in register_skill_paths:
        surface_dir = nb_path / f".{surface}" / "skills"
        surface_dir.mkdir(parents=True, exist_ok=True)
        link_target = surface_dir / "karpathy-llm-wiki"
        skill_install_modes[surface] = _link_skill(link_target, bundle)

    # Write notebook.json.
    (nb_path / ".notebookai" / "notebook.json").write_text(
        meta.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    # Wiki bootstraps.
    (nb_path / "wiki" / "index.md").write_text(_WIKI_INDEX, encoding="utf-8")
    (nb_path / "wiki" / "log.md").write_text(_WIKI_LOG, encoding="utf-8")

    # Root-level docs.
    (nb_path / "AGENTS.md").write_text(_agents_md(meta), encoding="utf-8")
    (nb_path / "README.md").write_text(_readme(meta), encoding="utf-8")
    (nb_path / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")

    # Optional git init + initial commit.
    if git_enabled:
        try:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=nb_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "add", "-A"],
                cwd=nb_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=NotebookAI",
                    "-c",
                    "user.email=agent@notebookai.local",
                    "commit",
                    "-q",
                    "-m",
                    "chore: scaffold notebook",
                ],
                cwd=nb_path,
                check=True,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            log.warning(
                "scaffold.git_init_failed",
                root=str(nb_path),
                error=str(exc),
            )

    log.info(
        "scaffold.created",
        id=nb_id,
        root=str(nb_path),
        skill_install_modes=skill_install_modes,
    )

    return NotebookHandle(
        root=nb_path,
        meta=meta,
        extra={"_SYMLINK_OR_COPY": skill_install_modes},
    )
