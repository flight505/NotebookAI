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

This is a NotebookAI notebook. The `wiki/` directory is the substrate. `raw/` is
immutable source material. `chats/` is conversation history. Every agent
operation should produce exactly one git commit (when `git_enabled=true`).

## Operating principles

- Edit `wiki/` not `raw/`. The `raw/` tree is read-only after ingest.
- Use the `karpathy-llm-wiki` skill for compile, query, and lint operations.
- Every op is one commit. The commit message follows the template in
  `docs/CONTRACTS.md` § GitCommit conventions.

## Layout

```
.notebookai/        internal state (safe to delete; rebuilds)
.claude/skills/     Claude Code skill discovery path
.agents/skills/     agentskills.io skill discovery path
raw/                immutable source material
wiki/               compiled knowledge (LLM-maintained, human-editable)
  index.md          top-level table of contents
  log.md            human-readable operation log
chats/              conversations as markdown
```

## Skill

The wiki workflow lives in the bundled skill:

- `.claude/skills/karpathy-llm-wiki/SKILL.md`
- `.agents/skills/karpathy-llm-wiki/SKILL.md`

Both paths point to the same bundle. Read it before performing any ingest,
compile, query, or lint operation against this notebook.

## Do not edit

The agent must not write to:

- `raw/**` — immutable after ingest
- `.notebookai/index.db` — derived from filesystem
- `.notebookai/embeddings.db` — derived from filesystem
- `.git/**` — managed by the commit workflow

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
