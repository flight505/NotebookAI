"""IndexStore: SQLAlchemy + sqlite-vec persistence for the derived index.

``index.db`` (SQLAlchemy) holds row state. ``embeddings.db`` (raw sqlite3
with the ``sqlite-vec`` extension loaded) holds vectors in a ``vec0``
virtual table. They live side-by-side under ``<notebook>/.notebookai/``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import sqlite_vec
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from ulid import ULID

from .schema import (
    Base,
    ChunkKind,
    EmbeddingChunk,
    Notebook,
    SourceFile,
    SourceKind,
)

DEFAULT_DIM = 384


def _ulid() -> str:
    return str(ULID())


def _read_dim_from_notebook(notebook_root: Path) -> int:
    nb_json = notebook_root / ".notebookai" / "notebook.json"
    if not nb_json.is_file():
        return DEFAULT_DIM
    try:
        data = json.loads(nb_json.read_text(encoding="utf-8"))
        return int(data.get("embeddings", {}).get("dim", DEFAULT_DIM))
    except Exception:
        return DEFAULT_DIM


def _read_meta_from_notebook(notebook_root: Path) -> dict[str, Any] | None:
    nb_json = notebook_root / ".notebookai" / "notebook.json"
    if not nb_json.is_file():
        return None
    try:
        return json.loads(nb_json.read_text(encoding="utf-8"))
    except Exception:
        return None


class IndexStore:
    """Owns ``index.db`` (SQLAlchemy) and ``embeddings.db`` (sqlite-vec).

    Use :meth:`bootstrap` to create tables before any other call.
    """

    def __init__(self, notebook_root: Path) -> None:
        self.notebook_root = Path(notebook_root).resolve()
        self._nb_dir = self.notebook_root / ".notebookai"
        self._nb_dir.mkdir(parents=True, exist_ok=True)

        self.index_db_path = self._nb_dir / "index.db"
        self.embeddings_db_path = self._nb_dir / "embeddings.db"

        self.dim = _read_dim_from_notebook(self.notebook_root)

        self._engine = create_engine(
            f"sqlite:///{self.index_db_path}",
            future=True,
        )
        self._SessionLocal = sessionmaker(
            bind=self._engine, expire_on_commit=False, future=True
        )

        # Open the embeddings DB and load sqlite-vec.
        self._vec_conn: sqlite3.Connection = sqlite3.connect(
            str(self.embeddings_db_path)
        )
        try:
            self._vec_conn.enable_load_extension(True)
            self._vec_conn.load_extension(sqlite_vec.loadable_path())
            self._vec_conn.enable_load_extension(False)
        except Exception as exc:  # pragma: no cover - platform dependent
            raise RuntimeError(
                "Failed to load the sqlite-vec extension. "
                "Ensure the sqlite-vec wheel ships a binary for this platform "
                f"(macOS arm64 / Linux / etc.). Original error: {exc!r}"
            ) from exc

    # -- session helpers -------------------------------------------------

    @contextmanager
    def session(self) -> Iterable[Session]:
        s = self._SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # -- bootstrap -------------------------------------------------------

    def bootstrap(self) -> None:
        """Create tables (idempotent) and the sqlite-vec virtual table."""
        Base.metadata.create_all(self._engine)

        # Vec virtual table (idempotent).
        self._vec_conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS embeddings_vec "
            f"USING vec0(vec FLOAT[{self.dim}])"
        )
        self._vec_conn.commit()

        # Mirror notebook.json into the Notebook table if present.
        meta = _read_meta_from_notebook(self.notebook_root)
        if meta is not None and meta.get("id"):
            with self.session() as s:
                row = s.get(Notebook, meta["id"])
                if row is None:
                    s.add(
                        Notebook(
                            id=meta["id"],
                            name=meta.get("name", meta["id"]),
                            root_path=str(self.notebook_root),
                            schema_version=int(meta.get("schema_version", 1)),
                        )
                    )

    # -- source files ----------------------------------------------------

    def upsert_source_file(
        self,
        notebook_id: str,
        kind: SourceKind | str,
        path: str,
        size: int,
        sha256: str,
        mtime: float,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        """Insert or update a SourceFile row. Returns its ULID."""
        if isinstance(kind, str):
            kind = SourceKind(kind)
        with self.session() as s:
            existing = s.scalar(
                select(SourceFile).where(
                    SourceFile.notebook_id == notebook_id,
                    SourceFile.path == path,
                )
            )
            if existing is None:
                row = SourceFile(
                    id=_ulid(),
                    notebook_id=notebook_id,
                    kind=kind,
                    path=path,
                    size=size,
                    sha256=sha256,
                    mtime=mtime,
                    last_indexed_at=datetime.now(timezone.utc),
                    frontmatter=frontmatter,
                )
                s.add(row)
                return row.id
            existing.kind = kind
            existing.size = size
            existing.sha256 = sha256
            existing.mtime = mtime
            existing.last_indexed_at = datetime.now(timezone.utc)
            if frontmatter is not None:
                existing.frontmatter = frontmatter
            return existing.id

    def get_source_file(
        self, notebook_id: str, path: str
    ) -> SourceFile | None:
        with self.session() as s:
            row = s.scalar(
                select(SourceFile).where(
                    SourceFile.notebook_id == notebook_id,
                    SourceFile.path == path,
                )
            )
            if row is None:
                return None
            # detach for safe access outside session
            s.expunge(row)
            return row

    def delete_source_file(self, notebook_id: str, path: str) -> None:
        """Delete a SourceFile and cascade-remove its embedding rows."""
        with self.session() as s:
            row = s.scalar(
                select(SourceFile).where(
                    SourceFile.notebook_id == notebook_id,
                    SourceFile.path == path,
                )
            )
            if row is None:
                return
            chunk_rowids = [c.vec_rowid for c in row.chunks]
            s.delete(row)  # cascade removes EmbeddingChunk rows
        # Remove vec rows.
        if chunk_rowids:
            qmarks = ",".join("?" * len(chunk_rowids))
            self._vec_conn.execute(
                f"DELETE FROM embeddings_vec WHERE rowid IN ({qmarks})",
                chunk_rowids,
            )
            self._vec_conn.commit()

    # -- embedding chunks ------------------------------------------------

    def _vec_to_blob(self, vec: np.ndarray) -> bytes:
        v = np.asarray(vec, dtype=np.float32).reshape(-1)
        if v.shape[0] != self.dim:
            raise ValueError(
                f"vector dim {v.shape[0]} != configured dim {self.dim}"
            )
        return v.tobytes()

    def upsert_embedding_chunk(
        self,
        source_file_id: str,
        kind: ChunkKind | str,
        ord: int,
        text: str,
        vec: np.ndarray,
    ) -> str:
        """Persist (or replace) an embedding row.

        If a row already exists for (source_file_id, kind, ord) it is updated
        in place — both the SQLAlchemy row and the underlying vec row.
        """
        if isinstance(kind, str):
            kind = ChunkKind(kind)

        blob = self._vec_to_blob(vec)

        with self.session() as s:
            existing = s.scalar(
                select(EmbeddingChunk).where(
                    EmbeddingChunk.source_file_id == source_file_id,
                    EmbeddingChunk.kind == kind,
                    EmbeddingChunk.ord == ord,
                )
            )
            if existing is not None:
                # Replace vec row in place.
                self._vec_conn.execute(
                    "UPDATE embeddings_vec SET vec = ? WHERE rowid = ?",
                    (blob, existing.vec_rowid),
                )
                self._vec_conn.commit()
                existing.text = text
                existing.dim = self.dim
                return existing.id

            cur = self._vec_conn.execute(
                "INSERT INTO embeddings_vec(vec) VALUES (?)", (blob,)
            )
            vec_rowid = int(cur.lastrowid)
            self._vec_conn.commit()

            row = EmbeddingChunk(
                id=_ulid(),
                source_file_id=source_file_id,
                kind=kind,
                ord=ord,
                text=text,
                dim=self.dim,
                vec_rowid=vec_rowid,
            )
            s.add(row)
            return row.id

    def has_chunk(
        self,
        source_file_id: str,
        kind: ChunkKind | str,
        ord: int,
    ) -> bool:
        if isinstance(kind, str):
            kind = ChunkKind(kind)
        with self.session() as s:
            row = s.scalar(
                select(EmbeddingChunk).where(
                    EmbeddingChunk.source_file_id == source_file_id,
                    EmbeddingChunk.kind == kind,
                    EmbeddingChunk.ord == ord,
                )
            )
            return row is not None

    def count_chunks(
        self,
        notebook_id: str,
        kind: ChunkKind | str | None = None,
    ) -> int:
        from sqlalchemy import func  # local import

        with self.session() as s:
            q = (
                select(func.count(EmbeddingChunk.id))
                .join(SourceFile, SourceFile.id == EmbeddingChunk.source_file_id)
                .where(SourceFile.notebook_id == notebook_id)
            )
            if kind is not None:
                if isinstance(kind, str):
                    kind = ChunkKind(kind)
                q = q.where(EmbeddingChunk.kind == kind)
            return int(s.scalar(q) or 0)

    # -- search ---------------------------------------------------------

    def query_similar(
        self,
        query_vec: np.ndarray,
        kinds: tuple[str, ...] = ("wiki",),
        top_k: int = 8,
    ) -> list[tuple[str, str, float, str]]:
        """Vector search restricted to the given chunk kinds.

        Returns a list of ``(chunk_id, source_file_path, score, text)`` tuples,
        ordered by similarity (smaller distance first).
        """
        blob = self._vec_to_blob(query_vec)
        # Pull more than we want; we'll filter by kind after.
        oversample = max(top_k * 4, top_k + 8)
        rows = self._vec_conn.execute(
            "SELECT rowid, distance FROM embeddings_vec "
            "WHERE vec MATCH ? AND k = ? "
            "ORDER BY distance",
            (blob, oversample),
        ).fetchall()
        if not rows:
            return []
        rowids = [r[0] for r in rows]
        scores = {r[0]: float(r[1]) for r in rows}

        kind_set = {ChunkKind(k) if not isinstance(k, ChunkKind) else k for k in kinds}

        with self.session() as s:
            chunks = s.scalars(
                select(EmbeddingChunk).where(
                    EmbeddingChunk.vec_rowid.in_(rowids),
                )
            ).all()
            file_ids = {c.source_file_id for c in chunks}
            files = s.scalars(
                select(SourceFile).where(SourceFile.id.in_(file_ids))
            ).all()
            file_path_by_id = {f.id: f.path for f in files}
            results: list[tuple[str, str, float, str]] = []
            for c in chunks:
                if c.kind not in kind_set:
                    continue
                results.append(
                    (
                        c.id,
                        file_path_by_id.get(c.source_file_id, ""),
                        scores.get(c.vec_rowid, float("inf")),
                        c.text,
                    )
                )
        # Re-sort by score and trim to top_k.
        results.sort(key=lambda r: r[2])
        return results[:top_k]

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        try:
            self._vec_conn.close()
        except Exception:
            pass
        try:
            self._engine.dispose()
        except Exception:
            pass

    def __enter__(self) -> IndexStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
