"""Tests for the wiki-only degraded mode and smart dispatchers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from notebookai.agent import operations as agent_operations
from notebookai.agent.degraded import WikiOnlyMode
from notebookai.agent.events import AgentDone, AgentMessage, AgentUnavailable
from notebookai.agent.runtime import AgentRuntime
from notebookai.index import (
    ChunkKind,
    FakeEmbedder,
    IndexStore,
    SourceKind,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_notebook(root: Path, *, nb_id: str = "wikionly-nb") -> Path:
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
    (nb / "wiki" / "index.md").write_text(
        "# Knowledge Base Index\n\n", encoding="utf-8"
    )
    (nb / "wiki" / "log.md").write_text("# Wiki Log\n\n", encoding="utf-8")
    return nb


def _seed_index(nb: Path, *, articles: dict[str, str]) -> None:
    """Seed the embedding store with fake-embedded wiki articles."""
    store = IndexStore(nb)
    store.bootstrap()
    embedder = FakeEmbedder(dim=32)
    try:
        for path, body in articles.items():
            (nb / path).parent.mkdir(parents=True, exist_ok=True)
            (nb / path).write_text(body, encoding="utf-8")
            sf_id = store.upsert_source_file(
                notebook_id="wikionly-nb",
                kind=SourceKind.wiki,
                path=path,
                size=len(body),
                sha256=path,
                mtime=0.0,
            )
            vec = embedder.encode([body])[0]
            store.upsert_embedding_chunk(sf_id, ChunkKind.wiki, 0, body, vec)
    finally:
        store.close()


class _StubAdapter:
    """Stand-in for URL/PDF/YouTube adapters — returns a canned RawDocument."""

    def fetch(self, source: str):
        from notebookai.adapters.base import RawDocument

        return RawDocument(
            source_type="url",
            source_url=source,
            title="Test Article",
            body="This is the article body. It mentions wikilinks like [[other]].",
            published="2026-01-01",
        )


# ---------------------------------------------------------------------------
# WikiOnlyMode.ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_only_ingest_writes_raw_no_compile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    monkeypatch.setattr(
        "notebookai.agent.degraded.URLAdapter", _StubAdapter
    )

    mode = WikiOnlyMode(notebook_id="wikionly-nb")
    result = await mode.ingest(
        nb, source="https://example.com/article", source_type="url"
    )

    assert result.usage.get("degraded") is True
    # Raw file written.
    raw_files = list((nb / "raw").rglob("*.md"))
    assert raw_files, "raw markdown file was not written"
    raw_rel = raw_files[0].relative_to(nb).as_posix()

    # No new wiki/<topic>/ article created — only index.md and log.md updated.
    wiki_articles = [
        p
        for p in (nb / "wiki").rglob("*.md")
        if p.name not in {"index.md", "log.md"}
    ]
    assert wiki_articles == [], f"unexpected wiki articles: {wiki_articles}"

    # index.md got the pending entry, log.md got a line.
    index_text = (nb / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "Pending compilation" in index_text
    assert raw_rel in index_text
    log_text = (nb / "wiki" / "log.md").read_text(encoding="utf-8")
    assert "wiki-only mode" in log_text
    assert raw_rel in log_text


# ---------------------------------------------------------------------------
# WikiOnlyMode.query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_only_query_returns_chunks(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    _seed_index(
        nb,
        articles={
            "wiki/alpha.md": "alpha discusses neural networks and backprop",
            "wiki/bravo.md": "bravo is about quantum computing",
            "wiki/charlie.md": "charlie covers compilers and parsers",
        },
    )

    mode = WikiOnlyMode(embedder=FakeEmbedder(dim=32), notebook_id="wikionly-nb")
    result = await mode.query(nb, prompt="bravo is about quantum computing", top_k=3)

    assert result.usage.get("degraded") is True
    assert "I found these passages but cannot synthesize" in result.summary
    # Top-1 article snippet must appear.
    assert "bravo is about quantum computing" in result.summary
    assert "wiki-only mode" in result.summary


# ---------------------------------------------------------------------------
# WikiOnlyMode.lint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_only_lint_runs_passive_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    # Create a wiki article with a broken wikilink — passive watcher should
    # surface it as a finding.
    (nb / "wiki" / "page.md").write_text(
        "# Page\n\nLinks to [[does-not-exist]].\n", encoding="utf-8"
    )

    # Sentinel: ensure no AgentRuntime / SDK calls are attempted.
    def _explode(*_a, **_kw):  # pragma: no cover - defensive
        raise AssertionError("LLM path should not be entered")

    monkeypatch.setattr(
        "notebookai.agent.operations.lint", _explode
    )

    mode = WikiOnlyMode(notebook_id="wikionly-nb")
    result = await mode.lint(nb, mode="light")

    assert result.usage.get("degraded") is True
    # Passive findings for the broken wikilink are surfaced.
    assert "broken_wikilink" in result.summary
    assert "does-not-exist" in result.summary


# ---------------------------------------------------------------------------
# Smart dispatcher routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smart_dispatcher_routes_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    runtime = AgentRuntime()

    real_called = {"v": False}
    degraded_called = {"v": False}

    async def fake_real_ingest(rt, root, *, source, source_type=None):
        real_called["v"] = True
        return agent_operations.OperationResult(
            op="ingest",
            op_id="00000000000000000000000A",
            notebook_id="wikionly-nb",
            summary="real",
        )

    async def fake_degraded_ingest(self, root, *, source, source_type=None):
        degraded_called["v"] = True
        return agent_operations.OperationResult(
            op="ingest",
            op_id="00000000000000000000000B",
            notebook_id="wikionly-nb",
            summary="degraded",
            usage={"degraded": True},
        )

    monkeypatch.setattr(
        "notebookai.agent.operations.ingest", fake_real_ingest
    )
    monkeypatch.setattr(WikiOnlyMode, "ingest", fake_degraded_ingest)

    # creds available → real path
    monkeypatch.setattr(
        AgentRuntime, "credentials_available", lambda self: True
    )
    real_called["v"] = False
    degraded_called["v"] = False
    r = await agent_operations.smart_ingest(
        runtime, nb, source="https://x", source_type="url"
    )
    assert real_called["v"] is True
    assert degraded_called["v"] is False
    assert r.summary == "real"

    # creds unavailable → degraded path
    monkeypatch.setattr(
        AgentRuntime, "credentials_available", lambda self: False
    )
    real_called["v"] = False
    degraded_called["v"] = False
    r2 = await agent_operations.smart_ingest(
        runtime, nb, source="https://x", source_type="url"
    )
    assert real_called["v"] is False
    assert degraded_called["v"] is True
    assert r2.summary == "degraded"


# ---------------------------------------------------------------------------
# AgentUnavailable event firing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_unavailable_event_fires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    monkeypatch.setattr(
        "notebookai.agent.degraded.URLAdapter", _StubAdapter
    )

    mode = WikiOnlyMode(notebook_id="wikionly-nb")
    result = await mode.ingest(
        nb, source="https://example.com/x", source_type="url"
    )
    types = [type(ev) for ev in result.events]
    assert AgentUnavailable in types, f"missing AgentUnavailable in {types}"
    # The unavailable event must be the FIRST event so subscribers see the
    # mode change before any further work.
    assert types[0] is AgentUnavailable
    # And must be followed by terminal events for streaming compatibility.
    assert AgentMessage in types
    assert AgentDone in types
