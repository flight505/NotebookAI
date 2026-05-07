"""Tests for ``notebookai.library.scanner``."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notebookai.api.app import create_app
from notebookai.api.dependencies import AppConfig
from notebookai.library import (
    LibraryScanner,
    load_library_config,
    save_library_config,
)
from notebookai.library.demo import (
    DEMO_NOTEBOOK_ID,
    create_demo_notebook,
)
from notebookai.scaffold import create_notebook

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "notebooks"
    root.mkdir()
    return root


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------


def test_scan_empty_root(library_root: Path) -> None:
    scanner = LibraryScanner(library_root)
    assert scanner.scan() == []


def test_scan_finds_notebook(library_root: Path) -> None:
    handle = create_notebook(library_root, "Alpha", git_enabled=False)
    scanner = LibraryScanner(library_root)
    entries = scanner.scan()
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "alpha"
    assert e.name == "Alpha"
    assert e.path == str(handle.root.resolve())
    assert e.is_external is False
    # Two boilerplate files (index.md, log.md) are NOT counted as articles.
    assert e.article_count == 0
    assert e.created_at is not None
    assert e.last_op_at is not None


def test_scan_skips_trash(library_root: Path) -> None:
    create_notebook(library_root, "Real NB", git_enabled=False)
    trash = library_root / ".trash" / "old-id"
    trash.mkdir(parents=True)
    (trash / ".notebookai").mkdir()
    (trash / ".notebookai" / "notebook.json").write_text(
        json.dumps(
            {
                "id": "old-id",
                "name": "Old",
                "created_at": "2024-01-01T00:00:00Z",
                "schema_version": 1,
                "git_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    entries = LibraryScanner(library_root).scan()
    ids = [e.id for e in entries]
    assert "old-id" not in ids
    assert "real-nb" in ids


def test_scan_skips_broken_notebook(
    library_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = library_root / "half-built"
    broken.mkdir()
    (broken / ".notebookai").mkdir()
    # Note: no notebook.json.
    create_notebook(library_root, "Good", git_enabled=False)

    with caplog.at_level(logging.WARNING):
        entries = LibraryScanner(library_root).scan()
    ids = [e.id for e in entries]
    assert ids == ["good"]
    # We don't strictly require structlog goes through caplog, just that the
    # broken folder didn't raise and didn't appear in results.


def test_register_external(
    library_root: Path, tmp_path: Path, config_path: Path
) -> None:
    ext_root = tmp_path / "external"
    ext_root.mkdir()
    handle = create_notebook(ext_root, "Outside NB", git_enabled=False)

    scanner = LibraryScanner(library_root, config_path=config_path)
    entry = scanner.register_external(handle.root)
    assert entry.is_external is True
    assert entry.id == "outside-nb"

    # Persisted to config.
    cfg = json.loads(config_path.read_text("utf-8"))
    assert str(handle.root.resolve()) in cfg["extra_notebook_roots"]

    # New scanner instance picks it up via config.
    cfg2 = load_library_config(config_path)
    extras = [Path(p) for p in cfg2["extra_notebook_roots"]]
    fresh = LibraryScanner(library_root, extras, config_path=config_path)
    entries = fresh.scan()
    assert any(e.id == "outside-nb" and e.is_external for e in entries)


def test_register_external_rejects_relative(
    library_root: Path, config_path: Path
) -> None:
    scanner = LibraryScanner(library_root, config_path=config_path)
    with pytest.raises(ValueError, match="absolute"):
        scanner.register_external(Path("./not-absolute"))


def test_register_external_rejects_non_notebook(
    library_root: Path, tmp_path: Path, config_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    scanner = LibraryScanner(library_root, config_path=config_path)
    with pytest.raises(ValueError, match="not a notebook"):
        scanner.register_external(plain)


def test_deregister_external(
    library_root: Path, tmp_path: Path, config_path: Path
) -> None:
    ext_root = tmp_path / "external"
    ext_root.mkdir()
    handle = create_notebook(ext_root, "Drop Me", git_enabled=False)

    scanner = LibraryScanner(library_root, config_path=config_path)
    scanner.register_external(handle.root)
    assert any(e.id == "drop-me" for e in scanner.scan())

    scanner.deregister_external(handle.root)
    assert not any(e.id == "drop-me" for e in scanner.scan())
    cfg = json.loads(config_path.read_text("utf-8"))
    assert handle.root.resolve().as_posix() not in [
        Path(p).as_posix() for p in cfg["extra_notebook_roots"]
    ]


def test_article_count(library_root: Path) -> None:
    handle = create_notebook(library_root, "Counted", git_enabled=False)
    wiki = handle.root / "wiki"
    (wiki / "topic-a").mkdir()
    (wiki / "topic-a" / "first.md").write_text("# First\n", encoding="utf-8")
    (wiki / "topic-a" / "second.md").write_text("# Second\n", encoding="utf-8")
    (wiki / "topic-b").mkdir()
    (wiki / "topic-b" / "third.md").write_text("# Third\n", encoding="utf-8")

    entries = LibraryScanner(library_root).scan()
    assert len(entries) == 1
    assert entries[0].article_count == 3


def test_last_op_at_from_git(library_root: Path) -> None:
    handle = create_notebook(library_root, "Git Tracked", git_enabled=True)
    if not (handle.root / ".git").is_dir():
        pytest.skip("git not available in this environment")
    # Make a fresh commit so we have a deterministic %cI to compare.
    (handle.root / "wiki" / "note.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=handle.root, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "test commit",
        ],
        cwd=handle.root,
        check=True,
        capture_output=True,
    )
    expected = subprocess.check_output(
        ["git", "log", "-1", "--format=%cI"], cwd=handle.root
    ).decode().strip()

    entries = LibraryScanner(library_root).scan()
    assert entries[0].last_op_at == expected


def test_find_by_id(library_root: Path) -> None:
    create_notebook(library_root, "Hello World", git_enabled=False)
    scanner = LibraryScanner(library_root)
    assert scanner.find_by_id("hello-world") is not None
    assert scanner.find_by_id("not-here") is None


# ---------------------------------------------------------------------------
# Demo notebook
# ---------------------------------------------------------------------------


def test_create_demo_notebook(library_root: Path) -> None:
    entry = create_demo_notebook(library_root)
    assert entry.id == DEMO_NOTEBOOK_ID
    assert entry.name == "Demo Notebook"

    nb_root = Path(entry.path)
    # Three wiki articles + index + log.
    welcome = nb_root / "wiki" / "general" / "welcome.md"
    transformers = nb_root / "wiki" / "ml" / "transformers.md"
    how_works = nb_root / "wiki" / "general" / "how-this-wiki-works.md"
    index = nb_root / "wiki" / "index.md"
    for p in (welcome, transformers, how_works, index):
        assert p.is_file(), f"missing seeded file: {p}"

    # Each wiki article carries valid YAML-style frontmatter.
    for p in (welcome, transformers, how_works):
        text = p.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"missing frontmatter: {p}"
        assert "\n---\n" in text, f"unterminated frontmatter: {p}"
        assert "title:" in text.split("\n---\n", 1)[0]

    # Sample chat with frontmatter intact.
    chat_files = list((nb_root / "chats").glob("*.md"))
    assert len(chat_files) == 1
    chat_text = chat_files[0].read_text(encoding="utf-8")
    assert chat_text.startswith("---\n")
    assert 'chat_id: "demo-getting-started"' in chat_text
    assert 'model: "demo"' in chat_text

    # Index links to all 3 articles.
    index_text = index.read_text(encoding="utf-8")
    for slug in ("welcome", "transformers", "how-this-wiki-works"):
        assert f"[[{slug}]]" in index_text, f"index missing link to {slug}"


def test_demo_notebook_idempotent(library_root: Path) -> None:
    first = create_demo_notebook(library_root)
    # Mutate a seeded file to prove the second call doesn't overwrite it.
    welcome = Path(first.path) / "wiki" / "general" / "welcome.md"
    welcome.write_text("# Edited\n", encoding="utf-8")

    second = create_demo_notebook(library_root)
    assert second.id == first.id
    assert second.path == first.path
    assert welcome.read_text(encoding="utf-8") == "# Edited\n"


def test_api_demo_endpoint(tmp_path: Path) -> None:
    library_root = tmp_path / "notebooks"
    library_root.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(
        library_root=library_root,
        config_file=tmp_path / "config.json",
    )
    app = create_app(config=cfg)
    with TestClient(app) as client:
        r1 = client.post("/api/library/demo")
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["notebook"]["id"] == DEMO_NOTEBOOK_ID
        assert body1["notebook"]["name"] == "Demo Notebook"

        # Second call: same id, no error.
        r2 = client.post("/api/library/demo")
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["notebook"]["id"] == body1["notebook"]["id"]
        assert body2["notebook"]["path"] == body1["notebook"]["path"]


# ---------------------------------------------------------------------------
# Config round-trip
# ---------------------------------------------------------------------------


def test_config_round_trip(config_path: Path, tmp_path: Path) -> None:
    initial = load_library_config(config_path)
    assert initial["schema_version"] == 1
    assert initial["extra_notebook_roots"] == []

    initial["extra_notebook_roots"].append(str(tmp_path / "somewhere"))
    save_library_config(config_path, initial)

    reread = load_library_config(config_path)
    assert reread["extra_notebook_roots"] == [str(tmp_path / "somewhere")]
    assert reread["schema_version"] == 1
    assert "default_agent_model" in reread
