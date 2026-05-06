"""Library scanner — discover notebooks across configured roots.

Implements ``LibraryScanner.scan`` which walks both the canonical
``library_root`` and any externally registered ``extra_notebook_roots``
recorded in ``~/NotebookAI/config.json``. A folder qualifies as a notebook
if and only if it contains ``.notebookai/notebook.json``.

Half-scaffolded notebooks (folders with ``.notebookai/`` but no valid
``notebook.json``) are logged as warnings and skipped — never raise from
``scan()``.

No caching is performed today: scans are cheap (``rglob`` over a single
``wiki/`` tree per notebook). If notebook counts grow into the hundreds we
can add an mtime-keyed cache later.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class NotebookEntry(BaseModel):
    """One entry in the library listing.

    The shape is what the API surfaces to the frontend; see ``CONTRACTS.md``
    § Decisions row 4.
    """

    id: str
    name: str
    path: str  # absolute path
    created_at: str | None = None
    last_op_at: str | None = None
    article_count: int = 0
    chat_count: int = 0
    is_external: bool = False
    git_enabled: bool = False


class Library(BaseModel):
    """A scan result wrapper. Currently just a list, but typed so callers
    can extend (e.g. to surface scan-time warnings) without a churny rename."""

    entries: list[NotebookEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


_DEFAULT_SCHEMA_VERSION = 1


def _default_config(library_root: Path | None = None) -> dict:
    root = library_root or (Path.home() / "NotebookAI" / "notebooks")
    return {
        "schema_version": _DEFAULT_SCHEMA_VERSION,
        "library_root": str(root),
        "extra_notebook_roots": [],
        "default_agent_model": "claude-sonnet-4-6",
        "default_lint_model": "claude-haiku-4-5-20251001",
    }


def load_library_config(config_path: Path) -> dict:
    """Read ``~/NotebookAI/config.json``. Creates with defaults if missing."""
    config_path = Path(config_path).expanduser()
    if not config_path.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        cfg = _default_config()
        config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return cfg
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("library.config_unreadable", path=str(config_path), error=str(exc))
        return _default_config()
    # Merge with defaults to fill missing keys.
    merged = _default_config()
    merged.update(data)
    if "extra_notebook_roots" not in data:
        merged["extra_notebook_roots"] = []
    return merged


def save_library_config(config_path: Path, config: dict) -> None:
    """Write the library config atomically (best-effort)."""
    config_path = Path(config_path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal probes
# ---------------------------------------------------------------------------


def _read_notebook_meta(root: Path) -> dict | None:
    meta_path = root / ".notebookai" / "notebook.json"
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("library.meta_not_object", path=str(meta_path))
            return None
        return data
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "library.meta_unreadable", path=str(meta_path), error=str(exc)
        )
        return None


def _last_op_at(root: Path) -> str | None:
    """Return ``git log -1 --format=%cI`` if available, else ``mtime``."""
    if (root / ".git").is_dir():
        try:
            out = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            txt = (out.stdout or "").strip()
            if txt:
                return txt
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        ts = datetime.fromtimestamp(root.stat().st_mtime, tz=timezone.utc)
        return ts.isoformat()
    except OSError:
        return None


def _article_count(root: Path) -> int:
    wiki = root / "wiki"
    if not wiki.is_dir():
        return 0
    # Count *.md but exclude the bookkeeping files at the root.
    count = 0
    for md in wiki.rglob("*.md"):
        rel = md.relative_to(wiki)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        count += 1
    return count


def _chat_count(root: Path) -> int:
    chats = root / "chats"
    if not chats.is_dir():
        return 0
    return sum(1 for _ in chats.rglob("*.md"))


def _entry_for(root: Path, *, is_external: bool) -> NotebookEntry | None:
    meta = _read_notebook_meta(root)
    if meta is None:
        return None
    nb_id = str(meta.get("id") or root.name)
    name = str(meta.get("name") or root.name)
    return NotebookEntry(
        id=nb_id,
        name=name,
        path=str(root.resolve()),
        created_at=meta.get("created_at"),
        last_op_at=_last_op_at(root),
        article_count=_article_count(root),
        chat_count=_chat_count(root),
        is_external=is_external,
        git_enabled=bool(meta.get("git_enabled", False))
        or (root / ".git").is_dir(),
    )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class LibraryScanner:
    """Walk the configured roots and return notebook entries.

    The scanner does not own the config file directly; callers pass in
    ``library_root`` and ``extra_roots`` as resolved paths. A higher-level
    wrapper (the API router) loads ``config.json`` and feeds them in.
    Mutating helpers (``register_external`` / ``deregister_external``) take
    a ``config_path`` so they can persist updates.
    """

    def __init__(
        self,
        library_root: Path,
        extra_roots: Iterable[Path] = (),
        *,
        config_path: Path | None = None,
    ) -> None:
        self.library_root = Path(library_root).expanduser()
        self.extra_roots = [Path(p).expanduser() for p in extra_roots]
        self.config_path = (
            Path(config_path).expanduser() if config_path is not None else None
        )

    # ------------------------------------------------------------------ scan

    def scan(self) -> list[NotebookEntry]:
        entries: list[NotebookEntry] = []

        # First-run convenience: create the library root lazily so a fresh
        # machine just works without the user pre-creating the directory.
        if not self.library_root.exists():
            try:
                self.library_root.mkdir(parents=True, exist_ok=True)
                log.info(
                    "library.library_root_created",
                    path=str(self.library_root),
                )
            except OSError as exc:
                log.warning(
                    "library.library_root_create_failed",
                    path=str(self.library_root),
                    error=str(exc),
                )

        if self.library_root.is_dir():
            for child in sorted(self.library_root.iterdir()):
                # Skip dotfolders (.trash/, .notebookai/, .DS_Store).
                if not child.is_dir() or child.name.startswith("."):
                    continue
                # Skip if the .notebookai dir exists but is broken — log+skip.
                if (child / ".notebookai").is_dir() and not (
                    child / ".notebookai" / "notebook.json"
                ).is_file():
                    log.warning(
                        "library.skipping_broken_notebook",
                        path=str(child),
                        reason="missing_notebook_json",
                    )
                    continue
                entry = _entry_for(child, is_external=False)
                if entry is not None:
                    entries.append(entry)

        for ext in self.extra_roots:
            ext_path = ext.resolve() if ext.exists() else ext
            if not ext_path.is_dir():
                log.warning(
                    "library.extra_root_missing", path=str(ext_path)
                )
                continue
            entry = _entry_for(ext_path, is_external=True)
            if entry is None:
                log.warning(
                    "library.extra_root_not_a_notebook", path=str(ext_path)
                )
                continue
            entries.append(entry)

        return entries

    # ------------------------------------------------------------- mutators

    def register_external(self, path: Path) -> NotebookEntry:
        """Validate + add ``path`` to ``extra_notebook_roots``.

        Raises ``ValueError`` if the path is not absolute, doesn't exist, or
        isn't a notebook (no ``.notebookai/notebook.json``).
        """
        target = Path(path)
        if not target.is_absolute():
            raise ValueError(f"path must be absolute: {target}")
        target = target.expanduser().resolve()
        if not target.is_dir():
            raise ValueError(f"path is not a directory: {target}")
        if not (target / ".notebookai" / "notebook.json").is_file():
            raise ValueError(
                f"not a notebook (missing .notebookai/notebook.json): {target}"
            )

        # Persist (if we have a config_path).
        if self.config_path is not None:
            cfg = load_library_config(self.config_path)
            extras = list(cfg.get("extra_notebook_roots", []) or [])
            if str(target) not in extras:
                extras.append(str(target))
            cfg["extra_notebook_roots"] = extras
            save_library_config(self.config_path, cfg)

        # In-memory mirror.
        if target not in self.extra_roots:
            self.extra_roots.append(target)

        entry = _entry_for(target, is_external=True)
        if entry is None:  # pragma: no cover - validated above
            raise ValueError(f"could not read notebook meta at {target}")
        return entry

    def deregister_external(self, path: Path) -> None:
        target = Path(path).expanduser().resolve()
        if self.config_path is not None:
            cfg = load_library_config(self.config_path)
            extras = [
                p
                for p in (cfg.get("extra_notebook_roots", []) or [])
                if Path(p).expanduser().resolve() != target
            ]
            cfg["extra_notebook_roots"] = extras
            save_library_config(self.config_path, cfg)
        self.extra_roots = [
            p for p in self.extra_roots if p.resolve() != target
        ]

    def find_by_id(self, id: str) -> NotebookEntry | None:
        for entry in self.scan():
            if entry.id == id:
                return entry
        return None


__all__ = [
    "Library",
    "LibraryScanner",
    "NotebookEntry",
    "load_library_config",
    "save_library_config",
]
