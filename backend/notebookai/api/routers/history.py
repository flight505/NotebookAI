"""History router: git log / show — falls back to oplog when git disabled."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    get_notebook_meta,
    resolve_notebook_root,
)

router = APIRouter(prefix="/notebooks/{notebook_id}/history", tags=["history"])


class HistoryEntry(BaseModel):
    sha: str
    author: str | None = None
    created_at: str | None = None
    subject: str
    body: str = ""


class HistoryDetail(HistoryEntry):
    diff: str = ""


def _git_history(root: Path, *, limit: int, since_sha: str | None) -> list[HistoryEntry]:
    rng = f"{since_sha}..HEAD" if since_sha else None
    cmd = [
        "git",
        "log",
        f"-n{limit}",
        "--pretty=%H%x1f%an%x1f%aI%x1f%s%x1f%b%x1e",
    ]
    if rng:
        cmd.append(rng)
    cmd.extend(["--", "."])
    try:
        out = subprocess.run(
            cmd,
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"git failed: {exc}") from exc

    entries: list[HistoryEntry] = []
    for chunk in (out.stdout or "").split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        sha, author, created_at, subject = parts[0], parts[1], parts[2], parts[3]
        body = parts[4] if len(parts) > 4 else ""
        entries.append(
            HistoryEntry(
                sha=sha,
                author=author,
                created_at=created_at,
                subject=subject,
                body=body,
            )
        )
    return entries


def _oplog_history(root: Path, *, limit: int) -> list[HistoryEntry]:
    p = root / ".notebookai" / "oplog.jsonl"
    if not p.is_file():
        return []
    out: list[HistoryEntry] = []
    for raw in reversed(p.read_text(encoding="utf-8").splitlines()):
        if not raw.strip():
            continue
        try:
            obj: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            continue
        out.append(
            HistoryEntry(
                sha=str(obj.get("op_id") or obj.get("id") or ""),
                author=str(obj.get("author") or "agent"),
                created_at=str(obj.get("ts") or obj.get("created_at") or ""),
                subject=f"[{obj.get('op','op')}] {obj.get('summary','')}",
                body="",
            )
        )
        if len(out) >= limit:
            break
    return out


@router.get("", response_model=list[HistoryEntry])
def list_history(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    since_sha: Annotated[str | None, Query()] = None,
) -> list[HistoryEntry]:
    root = resolve_notebook_root(notebook_id, config)
    meta = get_notebook_meta(notebook_id, config)
    if not meta.git_enabled:
        return _oplog_history(root, limit=limit)
    return _git_history(root, limit=limit, since_sha=since_sha)


@router.get("/{sha}", response_model=HistoryDetail)
def get_history_entry(
    notebook_id: str,
    sha: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> HistoryDetail:
    root = resolve_notebook_root(notebook_id, config)
    meta = get_notebook_meta(notebook_id, config)
    if not meta.git_enabled:
        # Look up in oplog by id.
        for entry in _oplog_history(root, limit=1000):
            if entry.sha == sha:
                return HistoryDetail(**entry.model_dump(), diff="")
        raise HTTPException(status_code=404, detail="oplog entry not found")

    try:
        out = subprocess.run(
            ["git", "show", "--pretty=full", "--stat", sha],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"git failed: {exc}") from exc
    if out.returncode != 0:
        raise HTTPException(status_code=404, detail="commit not found")

    show = out.stdout or ""
    # Crude header parse: first line is "commit <sha>".
    header_lines: list[str] = []
    body_lines: list[str] = []
    diff_started = False
    for line in show.splitlines():
        if line.startswith("diff --git") or line.startswith(" "):
            diff_started = True
        if diff_started:
            body_lines.append(line)
        else:
            header_lines.append(line)
    return HistoryDetail(
        sha=sha,
        subject=next((ln for ln in header_lines if ln and not ln.startswith(("commit ", "Author", "Date", "Commit"))), ""),
        body="\n".join(header_lines),
        diff="\n".join(body_lines),
    )


__all__ = ["router"]
