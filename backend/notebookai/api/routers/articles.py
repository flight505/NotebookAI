"""Articles router: list / read / write wiki pages + backlinks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    resolve_notebook_root,
)

router = APIRouter(prefix="/notebooks/{notebook_id}/articles", tags=["articles"])


class ArticleSummary(BaseModel):
    path: str
    title: str


class ArticleContent(BaseModel):
    path: str
    title: str
    content: str


class WriteArticleRequest(BaseModel):
    content: str


class BacklinksResponse(BaseModel):
    path: str
    backlinks: list[str]


_HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]")


def _resolve_article_path(notebook_root: Path, raw_path: str) -> Path:
    """Resolve a wiki-relative path safely.

    Rejects empty paths, absolute paths, traversal that escapes ``wiki/``.
    """
    decoded = unquote(raw_path or "")
    if not decoded or decoded.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid article path")
    wiki_root = (notebook_root / "wiki").resolve()
    try:
        candidate = (wiki_root / decoded).resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid path: {exc}") from exc
    try:
        candidate.relative_to(wiki_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path escapes wiki/") from exc
    if candidate.is_dir():
        raise HTTPException(status_code=400, detail="path is a directory")
    return candidate


def _extract_title(text: str, fallback: str) -> str:
    match = _HEADING_RE.search(text or "")
    if match:
        return match.group(1).strip()
    return fallback


def _commit_human_edit(notebook_root: Path, rel_path: str) -> None:
    """Commit a human edit to the wiki; ignore failures."""
    meta_path = notebook_root / ".notebookai" / "notebook.json"
    try:
        import json as _json

        meta: dict[str, Any] = _json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        meta = {}
    if not meta.get("git_enabled", True):
        return
    if not (notebook_root / ".git").is_dir():
        return
    try:
        subprocess.run(
            ["git", "add", "--", rel_path],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=NotebookAI Human",
                "-c",
                "user.email=human@notebookai.local",
                "commit",
                "--allow-empty",
                "-m",
                f"[human-edit] update {rel_path}",
            ],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
        )
    except (subprocess.SubprocessError, OSError):
        pass


@router.get("", response_model=list[ArticleSummary])
def list_articles(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> list[ArticleSummary]:
    root = resolve_notebook_root(notebook_id, config)
    wiki = root / "wiki"
    if not wiki.is_dir():
        return []
    out: list[ArticleSummary] = []
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(wiki).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(ArticleSummary(path=rel, title=_extract_title(text, rel)))
    return out


@router.get("/{path:path}/backlinks", response_model=BacklinksResponse)
def article_backlinks(
    notebook_id: str,
    path: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> BacklinksResponse:
    root = resolve_notebook_root(notebook_id, config)
    target = _resolve_article_path(root, path)
    wiki = (root / "wiki").resolve()
    target_rel = target.relative_to(wiki).as_posix()
    target_stem = target.stem  # e.g. "foo" for foo.md
    target_aliases = {target_stem, target_rel.removesuffix(".md")}

    backlinks: list[str] = []
    for other in wiki.rglob("*.md"):
        if other == target:
            continue
        try:
            text = other.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _WIKILINK_RE.findall(text):
            link = match.strip()
            if link in target_aliases or link == target_rel:
                rel_other = other.relative_to(wiki).as_posix()
                backlinks.append(rel_other)
                break
    backlinks.sort()
    return BacklinksResponse(path=target_rel, backlinks=backlinks)


@router.get("/{path:path}", response_model=ArticleContent)
def read_article(
    notebook_id: str,
    path: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> ArticleContent:
    root = resolve_notebook_root(notebook_id, config)
    target = _resolve_article_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="article not found")
    text = target.read_text(encoding="utf-8")
    rel = target.relative_to((root / "wiki").resolve()).as_posix()
    return ArticleContent(path=rel, title=_extract_title(text, rel), content=text)


@router.put("/{path:path}", response_model=ArticleContent)
def write_article(
    notebook_id: str,
    path: str,
    body: WriteArticleRequest,
    config: Annotated[AppConfig, Depends(get_config)],
) -> ArticleContent:
    root = resolve_notebook_root(notebook_id, config)
    target = _resolve_article_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    rel = target.relative_to(root).as_posix()  # e.g. wiki/foo.md
    _commit_human_edit(root, rel)
    wiki_rel = target.relative_to((root / "wiki").resolve()).as_posix()
    return ArticleContent(
        path=wiki_rel,
        title=_extract_title(body.content, wiki_rel),
        content=body.content,
    )


__all__ = ["router"]
