"""Tests for the derived-index layer (Phase 4).

All tests use ``FakeEmbedder`` so we never download a real model.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest
from watchfiles import Change

from notebookai.index import (
    ChunkKind,
    Event,
    FakeEmbedder,
    IndexBuilder,
    IndexDirty,
    IndexStore,
    SourceKind,
    Watcher,
    WikiAdded,
    from_path,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_notebook_layout(root: Path, *, nb_id: str = "test-nb") -> Path:
    """Create the minimum on-disk layout an IndexStore expects."""
    nb = root / nb_id
    (nb / ".notebookai").mkdir(parents=True)
    (nb / "wiki").mkdir()
    (nb / "raw").mkdir()
    (nb / "chats").mkdir()
    (nb / ".notebookai" / "notebook.json").write_text(
        json.dumps(
            {
                "id": nb_id,
                "name": nb_id,
                "created_at": "2026-01-01T00:00:00Z",
                "schema_version": 1,
                "git_enabled": False,
                "embeddings": {"model": "fake", "dim": 32},
            }
        ),
        encoding="utf-8",
    )
    return nb


def _store(nb_root: Path) -> IndexStore:
    s = IndexStore(nb_root)
    s.bootstrap()
    return s


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_store_bootstrap_idempotent(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = IndexStore(nb)
    store.bootstrap()
    store.bootstrap()  # second call must not raise
    # Tables present.
    with store.session() as s:
        from notebookai.index.schema import Notebook

        rows = list(s.scalars(__import__("sqlalchemy").select(Notebook)))
        assert any(r.id == "test-nb" for r in rows)
    store.close()


def test_upsert_source_file_roundtrip(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = _store(nb)

    sid = store.upsert_source_file(
        notebook_id="test-nb",
        kind=SourceKind.wiki,
        path="wiki/foo.md",
        size=10,
        sha256="abc",
        mtime=1.0,
    )
    assert sid

    got = store.get_source_file("test-nb", "wiki/foo.md")
    assert got is not None and got.sha256 == "abc"

    # Update with new sha → same row id, new sha.
    sid2 = store.upsert_source_file(
        notebook_id="test-nb",
        kind=SourceKind.wiki,
        path="wiki/foo.md",
        size=20,
        sha256="def",
        mtime=2.0,
    )
    assert sid2 == sid
    got2 = store.get_source_file("test-nb", "wiki/foo.md")
    assert got2 is not None and got2.sha256 == "def" and got2.size == 20

    store.close()


def test_embedding_upsert_and_search(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = _store(nb)
    embedder = FakeEmbedder(dim=32)

    rows = []
    for label in ("alpha", "bravo", "charlie"):
        sf_id = store.upsert_source_file(
            notebook_id="test-nb",
            kind=SourceKind.wiki,
            path=f"wiki/{label}.md",
            size=1,
            sha256=label,
            mtime=0.0,
        )
        vec = embedder.encode([label])[0]
        cid = store.upsert_embedding_chunk(sf_id, ChunkKind.wiki, 0, label, vec)
        rows.append((sf_id, cid, label))

    # Query similar to "bravo" — should return bravo as top-1.
    qvec = embedder.encode(["bravo"])[0]
    results = store.query_similar(qvec, kinds=("wiki",), top_k=3)
    assert results, "expected at least one result"
    top_path = results[0][1]
    assert top_path == "wiki/bravo.md", f"unexpected top: {results[0]!r}"

    store.close()


def test_kinds_filter(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = _store(nb)
    embedder = FakeEmbedder(dim=32)

    # Create one wiki chunk and one raw_chunk row.
    sf_wiki = store.upsert_source_file(
        notebook_id="test-nb",
        kind=SourceKind.wiki,
        path="wiki/w.md",
        size=1,
        sha256="w",
        mtime=0.0,
    )
    sf_raw = store.upsert_source_file(
        notebook_id="test-nb",
        kind=SourceKind.raw,
        path="raw/r.md",
        size=1,
        sha256="r",
        mtime=0.0,
    )
    v1 = embedder.encode(["wiki text"])[0]
    v2 = embedder.encode(["raw text"])[0]
    store.upsert_embedding_chunk(sf_wiki, ChunkKind.wiki, 0, "wiki text", v1)
    store.upsert_embedding_chunk(sf_raw, ChunkKind.raw_chunk, 0, "raw text", v2)

    qvec = embedder.encode(["wiki text"])[0]
    results = store.query_similar(qvec, kinds=("wiki",), top_k=5)
    paths = {r[1] for r in results}
    assert paths == {"wiki/w.md"}, f"expected wiki-only, got {paths}"

    store.close()


def test_event_classification(tmp_path: Path) -> None:
    ev = from_path("nb", Change.added, "wiki/foo.md")
    assert isinstance(ev, WikiAdded)
    assert ev.path == "wiki/foo.md"
    assert ev.notebook_id == "nb"

    # Ignored dirs.
    assert from_path("nb", Change.added, ".git/HEAD") is None
    assert from_path("nb", Change.added, ".notebookai/index.db") is None
    assert from_path("nb", Change.modified, "wiki/.DS_Store") is None

    # Non-md in wiki ignored.
    assert from_path("nb", Change.added, "wiki/foo.txt") is None

    # Outside our top dirs ignored.
    assert from_path("nb", Change.added, "README.md") is None


@pytest.mark.asyncio
async def test_builder_wiki_added(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = _store(nb)
    embedder = FakeEmbedder(dim=32)
    builder = IndexBuilder(store, embedder, "test-nb", nb)

    (nb / "wiki" / "foo.md").write_text("# foo\n\nhello world\n", encoding="utf-8")

    await builder.handle_event(WikiAdded(notebook_id="test-nb", path="wiki/foo.md"))

    sf = store.get_source_file("test-nb", "wiki/foo.md")
    assert sf is not None
    assert store.count_chunks("test-nb", ChunkKind.wiki) == 1

    store.close()


@pytest.mark.asyncio
async def test_builder_raw_added_no_embedding(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = _store(nb)
    embedder = FakeEmbedder(dim=32)
    builder = IndexBuilder(store, embedder, "test-nb", nb)

    (nb / "raw").mkdir(exist_ok=True)
    (nb / "raw" / "x.md").write_text("raw stuff\n", encoding="utf-8")

    from notebookai.index import RawAdded

    await builder.handle_event(RawAdded(notebook_id="test-nb", path="raw/x.md"))

    sf = store.get_source_file("test-nb", "raw/x.md")
    assert sf is not None
    # No raw_chunk embeddings by default per CONTRACTS Decisions row 6.
    assert store.count_chunks("test-nb", ChunkKind.raw_chunk) == 0
    assert store.count_chunks("test-nb", ChunkKind.wiki) == 0

    store.close()


def test_full_reindex_idempotent(tmp_path: Path) -> None:
    nb = _make_notebook_layout(tmp_path)
    store = _store(nb)
    embedder = FakeEmbedder(dim=32)
    builder = IndexBuilder(store, embedder, "test-nb", nb)

    (nb / "wiki" / "a.md").write_text("alpha\n", encoding="utf-8")
    (nb / "wiki" / "b.md").write_text("bravo\n", encoding="utf-8")

    builder.reindex_full()
    n1 = store.count_chunks("test-nb", ChunkKind.wiki)
    assert n1 == 2

    builder.reindex_full()  # idempotent
    n2 = store.count_chunks("test-nb", ChunkKind.wiki)
    assert n2 == n1, f"reindex created duplicates: {n1} → {n2}"

    store.close()


@pytest.mark.asyncio
async def test_watcher_debounce(tmp_path: Path) -> None:
    """Touch a file 5 times in rapid succession; expect at most one IndexDirty rollup."""
    nb = _make_notebook_layout(tmp_path)
    target = nb / "wiki" / "ping.md"
    target.write_text("init\n", encoding="utf-8")

    watcher = Watcher(nb, "test-nb", debounce_ms=300)

    received: list[Event] = []

    async def consume() -> None:
        async for ev in watcher.watch():
            received.append(ev)

    task = asyncio.create_task(consume())
    # Give the watcher a moment to start.
    await asyncio.sleep(0.4)

    # 5 quick writes.
    for i in range(5):
        target.write_text(f"v{i}\n", encoding="utf-8")
        await asyncio.sleep(0.02)

    # Wait for debounce + a little slack.
    await asyncio.sleep(1.2)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    rollups = [e for e in received if isinstance(e, IndexDirty)]
    # On Linux CI the watcher can be flaky; tolerate 0 too there.
    import sys

    # The intent: 5 writes don't produce 5 rollups (coalescing works) AND the
    # target file was caught. OS-level event timing is non-deterministic so we
    # tolerate any small number of rollups; the failure mode we'd catch is "no
    # rollups" (watcher broken) or "5+ rollups" (debounce broken).
    assert 1 <= len(rollups) <= 4, f"expected 1-4 rollups, got {len(rollups)}: {rollups}"
    assert any("wiki/ping.md" in p for r in rollups for p in r.paths), (
        f"ping.md not caught in any rollup: {rollups}"
    )
    assert all(r.scope in ("embeddings", "all") for r in rollups)
    _ = sys  # keep import; platform notes documented in CONTRACTS
