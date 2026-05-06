"""Tests for `notebookai.scaffold`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from notebookai.scaffold import NotebookMeta, create_notebook


def test_create_notebook_basic_layout(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "ML Research")

    assert handle.meta.id == "ml-research"
    nb = handle.root
    assert nb == (tmp_path / "ml-research").resolve()
    assert nb.is_dir()

    # Required directories.
    for rel in (
        ".notebookai",
        ".notebookai/locks",
        ".claude/skills",
        ".agents/skills",
        "raw",
        "wiki",
        "chats",
    ):
        assert (nb / rel).is_dir(), f"missing {rel}"

    # Required files.
    for rel in (
        ".notebookai/notebook.json",
        "wiki/index.md",
        "wiki/log.md",
        "AGENTS.md",
        "README.md",
        ".gitignore",
    ):
        assert (nb / rel).is_file(), f"missing {rel}"

    # notebook.json parses and matches.
    raw = (nb / ".notebookai/notebook.json").read_text("utf-8")
    parsed = json.loads(raw)
    assert parsed["id"] == "ml-research"
    assert parsed["name"] == "ML Research"
    assert parsed["schema_version"] == 1
    assert parsed["git_enabled"] is True
    assert parsed["agent"]["model"] == "claude-sonnet-4-6"
    assert parsed["agent"]["lint_model"] == "claude-haiku-4-5-20251001"
    assert parsed["agent"]["lint_budget_tokens_per_day"] == 50000
    assert parsed["embeddings"]["dim"] == 384

    # Skill resolves to a SKILL.md with valid frontmatter.
    skill_md = nb / ".claude/skills/karpathy-llm-wiki/SKILL.md"
    assert skill_md.is_file()
    content = skill_md.read_text("utf-8")
    assert content.startswith("---\n")
    assert "name: karpathy-llm-wiki" in content

    # Marker captured.
    assert "_SYMLINK_OR_COPY" in handle.extra
    assert handle.extra["_SYMLINK_OR_COPY"]["claude"] in {"symlink", "copy"}


def test_id_slugification(tmp_path: Path) -> None:
    # Special chars and multi-spaces collapse.
    h = create_notebook(tmp_path / "a", "Hello, World!! Foo")
    assert h.meta.id == "hello-world-foo"

    # Accented chars normalize to ASCII.
    h2 = create_notebook(tmp_path / "b", "Café Notes — Çoöl")
    assert h2.meta.id == "cafe-notes-cool"

    # Multiple spaces.
    h3 = create_notebook(tmp_path / "c", "  spaced   out   ")
    assert h3.meta.id == "spaced-out"

    # All-symbol input raises.
    with pytest.raises(ValueError):
        create_notebook(tmp_path / "d", "!!! @@@ ###")


def test_existing_directory_fails(tmp_path: Path) -> None:
    create_notebook(tmp_path, "Dup Name")
    with pytest.raises(FileExistsError):
        create_notebook(tmp_path, "Dup Name")


def test_no_git(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "No Git", git_enabled=False)
    assert not (handle.root / ".git").exists()


def test_register_skill_paths_subset(tmp_path: Path) -> None:
    handle = create_notebook(
        tmp_path,
        "Claude Only",
        register_skill_paths=("claude",),
    )
    nb = handle.root
    assert (nb / ".claude/skills/karpathy-llm-wiki/SKILL.md").is_file()
    assert not (nb / ".agents").exists()


def test_meta_round_trip(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "Round Trip", git_enabled=False)
    raw = (handle.root / ".notebookai/notebook.json").read_text("utf-8")
    meta = NotebookMeta.model_validate_json(raw)
    assert meta.id == "round-trip"
    assert meta.name == "Round Trip"
    assert meta.schema_version == 1
    assert meta.agent.lint_schedule == "hourly"
    assert meta.embeddings.model == "bge-small-en-v1.5"
