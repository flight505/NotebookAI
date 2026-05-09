"""IndexBuilder: glues filesystem events to the IndexStore + Embedder.

Wiki-pages-first per CONTRACTS § Decisions row 6: only ``wiki/**/*.md``
is embedded by default. Raw and chat files just become ``SourceFile`` rows.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np

from .embeddings import Embedder
from .events import (
    ChatsAdded,
    ChatsModified,
    Event,
    IndexDirty,
    RawAdded,
    RawDeleted,
    RawModified,
    WikiAdded,
    WikiDeleted,
    WikiModified,
)
from .schema import ChunkKind, SourceKind
from .store import IndexStore
from .watcher import Watcher


class _EmbedderLike(Protocol):  # pragma: no cover
    @property
    def dim(self) -> int: ...
    def encode(self, texts: list[str]) -> np.ndarray: ...


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


class IndexBuilder:
    """Apply filesystem events to the index."""

    def __init__(
        self,
        store: IndexStore,
        embedder: _EmbedderLike | Embedder,
        notebook_id: str,
        notebook_root: Path,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.notebook_id = notebook_id
        self.notebook_root = Path(notebook_root).resolve()

    # -- lifecycle ------------------------------------------------------

    def bootstrap(self) -> bool:
        """Initialise the index for this builder's notebook + embedder.

        Runs ``store.bootstrap`` (tables / vec0 / Notebook row), then
        reconciles the recorded embedder metadata against the live
        embedder. If the dim has changed, the chunk table is dropped and
        the vec0 virtual table is recreated at the new dim. Returns
        ``True`` when the caller should re-walk source files and re-embed.
        """
        self.store.bootstrap()
        model_name = getattr(self.embedder, "model_name", None) or type(
            self.embedder
        ).__name__
        try:
            dim = int(self.embedder.dim)
        except Exception:
            # If the embedder can't report its dim yet (lazy-load failure),
            # leave the recorded meta alone — better than mis-recording.
            return False
        return self.store.ensure_embedder_compatibility(
            self.notebook_id, model_name=model_name, dim=dim
        )

    # -- helpers --------------------------------------------------------

    def _abs(self, rel: str) -> Path:
        return (self.notebook_root / rel).resolve()

    def _stat(self, rel: str) -> tuple[int, float, str] | None:
        p = self._abs(rel)
        if not p.is_file():
            return None
        st = p.stat()
        return st.st_size, st.st_mtime, _sha256_of(p)

    def _embed_wiki_page(self, source_file_id: str, abs_path: Path) -> None:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
        vecs = self.embedder.encode([text])
        if vecs.shape[0] == 0:
            return
        self.store.upsert_embedding_chunk(
            source_file_id=source_file_id,
            kind=ChunkKind.wiki,
            ord=0,
            text=text,
            vec=vecs[0],
        )

    # -- single-event dispatch ------------------------------------------

    async def handle_event(self, event: Event) -> None:
        if isinstance(event, (WikiAdded, WikiModified)):
            self._handle_wiki_upsert(event.path)
        elif isinstance(event, WikiDeleted):
            self.store.delete_source_file(self.notebook_id, event.path)
        elif isinstance(event, (RawAdded, RawModified)):
            self._handle_source_only(event.path, SourceKind.raw)
        elif isinstance(event, RawDeleted):
            self.store.delete_source_file(self.notebook_id, event.path)
        elif isinstance(event, (ChatsAdded, ChatsModified)):
            self._handle_source_only(event.path, SourceKind.chat)
        elif isinstance(event, IndexDirty):
            # Rollup signal — handled by higher-level consumers.
            return

    def _handle_wiki_upsert(self, rel_path: str) -> None:
        stat = self._stat(rel_path)
        if stat is None:
            return
        size, mtime, sha = stat
        prior = self.store.get_source_file(self.notebook_id, rel_path)
        sf_id = self.store.upsert_source_file(
            notebook_id=self.notebook_id,
            kind=SourceKind.wiki,
            path=rel_path,
            size=size,
            sha256=sha,
            mtime=mtime,
        )
        # Skip re-embed only when content is unchanged AND a chunk row already
        # exists for this file; otherwise embed (insert or replace in place).
        if prior is not None and prior.sha256 == sha and self.store.has_chunk(
            sf_id, ChunkKind.wiki, 0
        ):
            return
        self._embed_wiki_page(sf_id, self._abs(rel_path))

    def _handle_source_only(self, rel_path: str, kind: SourceKind) -> None:
        stat = self._stat(rel_path)
        if stat is None:
            return
        size, mtime, sha = stat
        self.store.upsert_source_file(
            notebook_id=self.notebook_id,
            kind=kind,
            path=rel_path,
            size=size,
            sha256=sha,
            mtime=mtime,
        )

    # -- full reindex ---------------------------------------------------

    def reindex_full(self) -> None:
        """Walk wiki/ and raw/ on disk and ensure rows are up to date.

        Idempotent: skips wiki re-embed when sha256 is unchanged.
        """
        wiki_root = self.notebook_root / "wiki"
        if wiki_root.is_dir():
            for abs_path in wiki_root.rglob("*.md"):
                if not abs_path.is_file():
                    continue
                rel = abs_path.relative_to(self.notebook_root).as_posix()
                size = abs_path.stat().st_size
                mtime = abs_path.stat().st_mtime
                sha = _sha256_of(abs_path)

                prior = self.store.get_source_file(self.notebook_id, rel)
                sf_id = self.store.upsert_source_file(
                    notebook_id=self.notebook_id,
                    kind=SourceKind.wiki,
                    path=rel,
                    size=size,
                    sha256=sha,
                    mtime=mtime,
                )
                if (
                    prior is not None
                    and prior.sha256 == sha
                    and self.store.has_chunk(sf_id, ChunkKind.wiki, 0)
                ):
                    continue
                self._embed_wiki_page(sf_id, abs_path)

        raw_root = self.notebook_root / "raw"
        if raw_root.is_dir():
            for abs_path in raw_root.rglob("*"):
                if not abs_path.is_file():
                    continue
                rel = abs_path.relative_to(self.notebook_root).as_posix()
                size = abs_path.stat().st_size
                mtime = abs_path.stat().st_mtime
                sha = _sha256_of(abs_path)
                self.store.upsert_source_file(
                    notebook_id=self.notebook_id,
                    kind=SourceKind.raw,
                    path=rel,
                    size=size,
                    sha256=sha,
                    mtime=mtime,
                )

    # -- async run loop -------------------------------------------------

    async def run(self) -> None:
        """Bootstrap with a full reindex, then follow the watcher forever."""
        self.reindex_full()
        watcher = Watcher(self.notebook_root, self.notebook_id)
        async for event in watcher.watch():
            await self.handle_event(event)
