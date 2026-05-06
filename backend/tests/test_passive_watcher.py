"""Phase 10 — passive watcher tests.

These tests run entirely against the local filesystem; no LLM spend.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from notebookai.agent.passive_watcher import PassiveWatcher
from notebookai.index.events import RawAdded, WikiAdded
from notebookai.index.store import IndexStore


def _make_notebook(root: Path, *, nb_id: str = "nb") -> Path:
    """Minimum on-disk layout for a notebook + IndexStore."""
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


@pytest.mark.asyncio
async def test_orphan_raw_detection(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    raw_dir = nb / "raw" / "ml"
    raw_dir.mkdir(parents=True)
    (raw_dir / "foo.md").write_text("# raw foo\nbody\n", encoding="utf-8")
    # No wiki article cites foo.md.

    watcher = PassiveWatcher()
    findings = await watcher.scan(nb)
    kinds = [f.kind for f in findings]
    assert "orphan_raw" in kinds
    orphans = [f for f in findings if f.kind == "orphan_raw"]
    assert len(orphans) == 1
    assert orphans[0].path.endswith("foo.md")


@pytest.mark.asyncio
async def test_broken_wikilink_detection(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    (nb / "wiki" / "ml").mkdir()
    (nb / "wiki" / "ml" / "index.md").write_text(
        "# Index\nSee [[nonexistent]] for details.\n",
        encoding="utf-8",
    )

    watcher = PassiveWatcher()
    findings = await watcher.scan(nb)
    broken = [f for f in findings if f.kind == "broken_wikilink"]
    assert len(broken) == 1
    assert "nonexistent" in broken[0].message


@pytest.mark.asyncio
async def test_broken_path_link_detection(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    (nb / "wiki" / "ml").mkdir()
    (nb / "wiki" / "ml" / "a.md").write_text(
        "# A\n[click here](missing.md) for details.\n",
        encoding="utf-8",
    )

    watcher = PassiveWatcher()
    findings = await watcher.scan(nb)
    broken = [f for f in findings if f.kind == "broken_path_link"]
    assert len(broken) >= 1
    assert any("missing.md" in f.message for f in broken)


@pytest.mark.asyncio
async def test_no_findings_clean_notebook(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    # Wiki cites the raw via filename mention, no broken links.
    (nb / "raw" / "ml").mkdir(parents=True)
    (nb / "raw" / "ml" / "foo.md").write_text("body\n", encoding="utf-8")
    (nb / "wiki" / "topic.md").write_text(
        "# Topic\n\nReferences: foo.md (in raw/ml).\n", encoding="utf-8"
    )

    watcher = PassiveWatcher()
    findings = await watcher.scan(nb)
    assert findings == [], f"expected no findings, got {[f.kind for f in findings]}"


@pytest.mark.asyncio
async def test_on_event_incremental(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    watcher = PassiveWatcher()
    initial = await watcher.scan(nb)
    assert initial == []

    # Now write a wiki page with a broken wikilink and feed a WikiAdded event.
    (nb / "wiki" / "intro.md").write_text(
        "# Intro\nSee [[ghost]] for more.\n", encoding="utf-8"
    )
    ev = WikiAdded(notebook_id="nb", path="wiki/intro.md")
    findings = watcher.on_event(ev, notebook_root=nb)
    assert any(f.kind == "broken_wikilink" for f in findings)


@pytest.mark.asyncio
async def test_findings_persisted_to_index_db(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    (nb / "raw" / "ml").mkdir(parents=True)
    (nb / "raw" / "ml" / "foo.md").write_text("body\n", encoding="utf-8")

    store = IndexStore(nb)
    store.bootstrap()
    try:
        watcher = PassiveWatcher(store=store, notebook_id="nb")
        findings = await watcher.scan(nb)
        watcher.persist(findings)

        from notebookai.index.schema import LintFinding

        with store.session() as s:
            from sqlalchemy import select

            rows = list(s.scalars(select(LintFinding).where(LintFinding.notebook_id == "nb")))
        assert len(rows) >= 1
        kinds = [r.kind for r in rows]
        assert "orphan_raw" in kinds
    finally:
        store.close()


@pytest.mark.asyncio
async def test_on_event_raw_added_orphan(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    (nb / "raw" / "ml").mkdir(parents=True)
    new_raw = nb / "raw" / "ml" / "fresh.md"
    new_raw.write_text("body\n", encoding="utf-8")

    watcher = PassiveWatcher()
    findings = watcher.on_event(
        RawAdded(notebook_id="nb", path="raw/ml/fresh.md"),
        notebook_root=nb,
    )
    assert any(f.kind == "orphan_raw" for f in findings)
