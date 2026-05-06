"""Typed file-watcher events.

Names and payload shapes match CONTRACTS § FileWatcher events exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal, Union

try:
    from watchfiles import Change  # type: ignore
except Exception:  # pragma: no cover - watchfiles is required at runtime
    Change = None  # type: ignore


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawAdded:
    notebook_id: str
    path: str
    size: int = 0
    hash: str = ""
    _event_name: ClassVar[str] = "raw.added"


@dataclass(frozen=True, slots=True)
class RawModified:
    notebook_id: str
    path: str
    size: int = 0
    hash: str = ""
    _event_name: ClassVar[str] = "raw.modified"


@dataclass(frozen=True, slots=True)
class RawDeleted:
    notebook_id: str
    path: str
    _event_name: ClassVar[str] = "raw.deleted"


@dataclass(frozen=True, slots=True)
class WikiAdded:
    notebook_id: str
    path: str
    hash: str = ""
    _event_name: ClassVar[str] = "wiki.added"


@dataclass(frozen=True, slots=True)
class WikiModified:
    notebook_id: str
    path: str
    hash: str = ""
    _event_name: ClassVar[str] = "wiki.modified"


@dataclass(frozen=True, slots=True)
class WikiDeleted:
    notebook_id: str
    path: str
    _event_name: ClassVar[str] = "wiki.deleted"


@dataclass(frozen=True, slots=True)
class ChatsAdded:
    notebook_id: str
    path: str
    _event_name: ClassVar[str] = "chats.added"


@dataclass(frozen=True, slots=True)
class ChatsModified:
    notebook_id: str
    path: str
    _event_name: ClassVar[str] = "chats.modified"


IndexDirtyScope = Literal["embeddings", "fts", "backlinks", "all"]


@dataclass(frozen=True, slots=True)
class IndexDirty:
    notebook_id: str
    scope: IndexDirtyScope
    paths: tuple[str, ...] = field(default_factory=tuple)
    _event_name: ClassVar[str] = "index.dirty"


Event = Union[
    RawAdded,
    RawModified,
    RawDeleted,
    WikiAdded,
    WikiModified,
    WikiDeleted,
    ChatsAdded,
    ChatsModified,
    IndexDirty,
]


# ---------------------------------------------------------------------------
# Path → event classification
# ---------------------------------------------------------------------------


def _is_ignored(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    if not parts:
        return True
    if parts[0] in (".git", ".notebookai"):
        return True
    if parts[-1] == ".DS_Store":
        return True
    return False


def from_path(notebook_id: str, change_kind, rel_path: str) -> Event | None:
    """Classify a (change, relative-path) tuple into a typed event.

    ``rel_path`` is relative to the notebook root, using ``/`` separators.
    Returns ``None`` for anything we don't care about (ignored dirs, files
    outside the three top-level dirs, etc.).
    """
    if _is_ignored(rel_path):
        return None

    parts = rel_path.replace("\\", "/").split("/")
    top = parts[0]

    # `Change` enum values: 1=added, 2=modified, 3=deleted (per watchfiles).
    if Change is not None and isinstance(change_kind, Change):
        ck_name = change_kind.name  # "added" | "modified" | "deleted"
    else:
        # accept raw int / string for tests / forward-compat
        try:
            ck_name = {1: "added", 2: "modified", 3: "deleted"}[int(change_kind)]
        except (TypeError, ValueError, KeyError):
            ck_name = str(change_kind).split(".")[-1].lower()

    if top == "raw":
        if ck_name == "added":
            return RawAdded(notebook_id=notebook_id, path=rel_path)
        if ck_name == "modified":
            return RawModified(notebook_id=notebook_id, path=rel_path)
        if ck_name == "deleted":
            return RawDeleted(notebook_id=notebook_id, path=rel_path)

    if top == "wiki":
        # only markdown
        if not rel_path.endswith(".md"):
            return None
        if ck_name == "added":
            return WikiAdded(notebook_id=notebook_id, path=rel_path)
        if ck_name == "modified":
            return WikiModified(notebook_id=notebook_id, path=rel_path)
        if ck_name == "deleted":
            return WikiDeleted(notebook_id=notebook_id, path=rel_path)

    if top == "chats":
        if not rel_path.endswith(".md"):
            return None
        if ck_name == "added":
            return ChatsAdded(notebook_id=notebook_id, path=rel_path)
        if ck_name == "modified":
            return ChatsModified(notebook_id=notebook_id, path=rel_path)
        # chats.deleted is not in CONTRACTS event table — silently ignore.
        return None

    return None
