"""Derived index + file watcher.

Phase 4: SQLite/sqlite-vec persistence, embedding service, async file watcher,
and the index builder that ties them together.

Wiki-pages-first embedding strategy per CONTRACTS § Decisions row 6: only
``wiki/**/*.md`` is embedded by default. Raw chunks (``kind="raw_chunk"``) are
embedded only on explicit request.
"""

from __future__ import annotations

from .builder import IndexBuilder
from .embeddings import Embedder, FakeEmbedder
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
    from_path,
)
from .schema import (
    Base,
    ChunkKind,
    EmbeddingChunk,
    LintBudget,
    LintFinding,
    Notebook,
    SourceFile,
    SourceKind,
)
from .store import IndexStore
from .watcher import Watcher

__all__ = [
    # store / builder / embedder / watcher
    "IndexStore",
    "Embedder",
    "FakeEmbedder",
    "IndexBuilder",
    "Watcher",
    # schema
    "Base",
    "Notebook",
    "SourceFile",
    "EmbeddingChunk",
    "LintBudget",
    "LintFinding",
    "SourceKind",
    "ChunkKind",
    # events
    "Event",
    "RawAdded",
    "RawModified",
    "RawDeleted",
    "WikiAdded",
    "WikiModified",
    "WikiDeleted",
    "ChatsAdded",
    "ChatsModified",
    "IndexDirty",
    "from_path",
]
