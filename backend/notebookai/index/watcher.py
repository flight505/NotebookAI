"""Async file watcher.

Coalesces ``watchfiles`` events into typed CONTRACTS events and emits an
``IndexDirty`` rollup 500 ms after the last change in a burst. Ignores
``.git/**``, ``.notebookai/**``, and ``.DS_Store`` so the watcher never
self-triggers on its own writes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from watchfiles import Change, awatch

from .events import (
    Event,
    IndexDirty,
    IndexDirtyScope,
    from_path,
)

# Order matches CONTRACTS § FileWatcher events table.
_EVENT_ORDER = (
    "raw.added",
    "raw.modified",
    "raw.deleted",
    "wiki.added",
    "wiki.modified",
    "wiki.deleted",
    "chats.added",
    "chats.modified",
    "index.dirty",
)
_ORDER_INDEX = {name: i for i, name in enumerate(_EVENT_ORDER)}


def _watcher_filter(change: Change, raw_path: str) -> bool:
    """Return True to keep, False to ignore (watchfiles convention)."""
    p = raw_path.replace("\\", "/")
    parts = p.split("/")
    for seg in parts:
        if seg == ".git" or seg == ".notebookai":
            return False
    if parts and parts[-1] == ".DS_Store":
        return False
    return True


def _scope_for_paths(paths: list[str]) -> IndexDirtyScope:
    touched_wiki = any(p.startswith("wiki/") or "/wiki/" in p for p in paths)
    touched_chats = any(p.startswith("chats/") or "/chats/" in p for p in paths)
    touched_raw = any(p.startswith("raw/") or "/raw/" in p for p in paths)
    if touched_wiki and not touched_chats and not touched_raw:
        return "embeddings"
    if touched_chats and not touched_wiki and not touched_raw:
        return "fts"
    if touched_raw and not touched_wiki and not touched_chats:
        return "embeddings"
    return "all"


class Watcher:
    """Async watcher emitting typed events for one notebook."""

    def __init__(
        self,
        notebook_root: Path,
        notebook_id: str,
        *,
        debounce_ms: int = 500,
    ) -> None:
        self.notebook_root = Path(notebook_root).resolve()
        self.notebook_id = notebook_id
        self.debounce_ms = int(debounce_ms)

    def _to_rel(self, abs_path: str) -> str | None:
        try:
            rel = Path(abs_path).resolve().relative_to(self.notebook_root)
        except ValueError:
            return None
        return rel.as_posix()

    async def watch(self) -> AsyncIterator[Event]:
        """Yield events forever (until cancelled).

        Within a single watchfiles batch we coalesce raw events per path
        (latest change wins). After yielding the per-file events we yield
        a single ``IndexDirty`` rollup. ``watchfiles.awatch`` already
        debounces at the OS level using ``debounce`` (ms) and ``step``.
        """
        # Coalesce per-path: latest change kind wins.
        try:
            async for changes in awatch(
                str(self.notebook_root),
                watch_filter=_watcher_filter,
                debounce=self.debounce_ms,
                step=max(50, self.debounce_ms // 5),
                recursive=True,
            ):
                # Normalize to relative path; coalesce per path.
                latest: dict[str, Change] = {}
                for change_kind, raw_path in changes:
                    rel = self._to_rel(raw_path)
                    if rel is None:
                        continue
                    latest[rel] = change_kind

                events: list[Event] = []
                for rel, change_kind in latest.items():
                    ev = from_path(self.notebook_id, change_kind, rel)
                    if ev is not None:
                        events.append(ev)

                if not events:
                    continue

                # Emit per-file events in CONTRACTS order.
                events.sort(
                    key=lambda e: _ORDER_INDEX.get(
                        getattr(e, "_event_name", ""), 999
                    )
                )
                for ev in events:
                    yield ev

                # Rollup.
                paths = sorted({getattr(e, "path", "") for e in events if getattr(e, "path", "")})
                scope = _scope_for_paths(paths)
                yield IndexDirty(
                    notebook_id=self.notebook_id,
                    scope=scope,
                    paths=tuple(paths),
                )
        except asyncio.CancelledError:
            return
