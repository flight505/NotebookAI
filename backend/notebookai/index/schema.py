"""SQLAlchemy 2 declarative models for the derived index.

The ``index.db`` SQLite database persists row-shaped state derived from the
filesystem: notebooks, source files (raw/wiki/chats), embedding chunks, and
lint findings. Vectors themselves live in a separate ``embeddings.db`` backed
by ``sqlite-vec``; ``EmbeddingChunk.vec_rowid`` links to that table.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceKind(str, enum.Enum):
    """Top-level filesystem source classification."""

    wiki = "wiki"
    raw = "raw"
    chat = "chat"


class ChunkKind(str, enum.Enum):
    """Embedding chunk kind per CONTRACTS § Decisions row 6.

    Only ``wiki`` and ``raw_chunk`` exist. Chats are not embedded — they get
    FTS in Phase 9.
    """

    wiki = "wiki"
    raw_chunk = "raw_chunk"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Declarative base for the index.db tables."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class Notebook(Base):
    """Mirrors ``notebook.json``. Populated by :meth:`IndexStore.bootstrap`.

    One row per notebook DB (typically one).
    """

    __tablename__ = "notebooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    source_files: Mapped[list[SourceFile]] = relationship(
        back_populates="notebook",
        cascade="all, delete-orphan",
    )


class SourceFile(Base):
    """A file under ``raw/``, ``wiki/``, or ``chats/``.

    Path is unique per notebook. Sha256 + mtime drive idempotent re-indexing.
    """

    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("notebook_id", "path", name="uq_source_files_nb_path"),
        Index("ix_source_files_nb_kind", "notebook_id", "kind"),
        Index("ix_source_files_nb_path", "notebook_id", "path"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[SourceKind] = mapped_column(
        SAEnum(SourceKind, name="source_kind"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_indexed_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    frontmatter: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    notebook: Mapped[Notebook] = relationship(back_populates="source_files")
    chunks: Mapped[list[EmbeddingChunk]] = relationship(
        back_populates="source_file",
        cascade="all, delete-orphan",
    )


class EmbeddingChunk(Base):
    """One embedding row.

    For ``kind="wiki"`` the row is whole-page (``ord=0``). For
    ``kind="raw_chunk"`` ``ord`` is the chunk ordinal within the file.
    ``vec_rowid`` links to the sqlite-vec virtual table in ``embeddings.db``.
    """

    __tablename__ = "embedding_chunks"
    __table_args__ = (
        Index("ix_chunks_sf_kind_ord", "source_file_id", "kind", "ord"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ChunkKind] = mapped_column(
        SAEnum(ChunkKind, name="chunk_kind"),
        nullable=False,
    )
    ord: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vec_rowid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    source_file: Mapped[SourceFile] = relationship(back_populates="chunks")


class LintFinding(Base):
    """Placeholder for Phase 10. We just need the table now.

    A finding produced by the scheduled Haiku lint pass.
    """

    __tablename__ = "lint_findings"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
