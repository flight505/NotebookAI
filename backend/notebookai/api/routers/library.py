"""Library router: list discovered notebooks + register externals."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from notebookai.api.dependencies import AppConfig, get_config

router = APIRouter(prefix="/library", tags=["library"])


class LibraryEntry(BaseModel):
    id: str
    name: str
    path: str
    created_at: str | None = None
    last_op_at: str | None = None
    article_count: int = 0
    is_external: bool = False


class RegisterRequest(BaseModel):
    path: str = Field(min_length=1)


def _read_notebook_meta(root: Path) -> dict[str, Any] | None:
    meta_path = root / ".notebookai" / "notebook.json"
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _last_op_at(root: Path) -> str | None:
    """Use `git log -1 --format=%cI` if available; else mtime of root."""
    if (root / ".git").is_dir():
        try:
            out = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            txt = (out.stdout or "").strip()
            if txt:
                return txt
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        ts = datetime.fromtimestamp(root.stat().st_mtime, tz=timezone.utc)
        return ts.isoformat()
    except OSError:
        return None


def _article_count(root: Path) -> int:
    wiki = root / "wiki"
    if not wiki.is_dir():
        return 0
    return sum(1 for _ in wiki.rglob("*.md"))


def _entry_for(root: Path, *, is_external: bool) -> LibraryEntry | None:
    meta = _read_notebook_meta(root)
    if meta is None:
        return None
    return LibraryEntry(
        id=str(meta.get("id") or root.name),
        name=str(meta.get("name") or root.name),
        path=str(root.resolve()),
        created_at=meta.get("created_at"),
        last_op_at=_last_op_at(root),
        article_count=_article_count(root),
        is_external=is_external,
    )


@router.get("", response_model=list[LibraryEntry])
def list_library(
    config: Annotated[AppConfig, Depends(get_config)],
) -> list[LibraryEntry]:
    entries: list[LibraryEntry] = []
    root = config.library_root
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            entry = _entry_for(child, is_external=False)
            if entry is not None:
                entries.append(entry)

    cfg = config.read_config()
    for ext in cfg.get("extra_notebook_roots", []) or []:
        ext_path = Path(ext).expanduser()
        entry = _entry_for(ext_path, is_external=True)
        if entry is not None:
            entries.append(entry)

    return entries


@router.post("/register", response_model=LibraryEntry)
def register_external(
    body: RegisterRequest,
    config: Annotated[AppConfig, Depends(get_config)],
) -> LibraryEntry:
    path = Path(body.path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="path is not a directory")
    if not (path / ".notebookai" / "notebook.json").is_file():
        raise HTTPException(
            status_code=400,
            detail="not a notebook (missing .notebookai/notebook.json)",
        )

    cfg = config.read_config()
    extras = list(cfg.get("extra_notebook_roots", []) or [])
    if str(path) not in extras:
        extras.append(str(path))
    cfg["extra_notebook_roots"] = extras
    config.write_config(cfg)

    entry = _entry_for(path, is_external=True)
    if entry is None:
        raise HTTPException(status_code=500, detail="failed to read notebook meta")
    return entry


__all__ = ["router"]
