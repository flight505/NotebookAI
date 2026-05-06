"""Operation log router: merge wiki/log.md + git log + oplog.jsonl."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    get_notebook_meta,
    resolve_notebook_root,
)

router = APIRouter(prefix="/notebooks/{notebook_id}/log", tags=["log"])


class LogEntry(BaseModel):
    op: str | None = None
    summary: str
    source: str  # "git" | "log.md" | "oplog"
    sha: str | None = None
    created_at: str | None = None


_OP_PATTERN = re.compile(r"^\[(?P<op>[a-z\-]+)\]\s*(?P<rest>.*)$")


def _git_log(notebook_root: Path, *, limit: int) -> list[LogEntry]:
    try:
        out = subprocess.run(
            [
                "git",
                "log",
                f"-n{limit}",
                "--pretty=%H%x1f%cI%x1f%s",
            ],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    entries: list[LogEntry] = []
    for line in (out.stdout or "").splitlines():
        try:
            sha, created_at, subject = line.split("\x1f", 2)
        except ValueError:
            continue
        op = None
        m = _OP_PATTERN.match(subject)
        if m:
            op = m.group("op")
        entries.append(
            LogEntry(op=op, summary=subject, source="git", sha=sha, created_at=created_at)
        )
    return entries


def _oplog_entries(notebook_root: Path) -> list[LogEntry]:
    p = notebook_root / ".notebookai" / "oplog.jsonl"
    if not p.is_file():
        return []
    out: list[LogEntry] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            continue
        out.append(
            LogEntry(
                op=str(obj.get("op")) if obj.get("op") else None,
                summary=str(obj.get("summary") or ""),
                source="oplog",
                sha=str(obj.get("op_id")) if obj.get("op_id") else None,
                created_at=str(obj.get("ts") or obj.get("created_at") or ""),
            )
        )
    return out


def _wiki_log_entries(notebook_root: Path) -> list[LogEntry]:
    p = notebook_root / "wiki" / "log.md"
    if not p.is_file():
        return []
    out: list[LogEntry] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        out.append(LogEntry(op=None, summary=line[2:], source="log.md"))
    return out


@router.get("", response_model=list[LogEntry])
def get_log(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
    op: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[LogEntry]:
    root = resolve_notebook_root(notebook_id, config)
    meta = get_notebook_meta(notebook_id, config)

    entries: list[LogEntry] = []
    if meta.git_enabled:
        entries.extend(_git_log(root, limit=limit))
    else:
        entries.extend(_oplog_entries(root))
    entries.extend(_wiki_log_entries(root))

    # Dedup by (sha, summary) tuple.
    seen: set[tuple[str | None, str]] = set()
    unique: list[LogEntry] = []
    for e in entries:
        key = (e.sha, e.summary)
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    if op:
        unique = [e for e in unique if (e.op or "") == op]
    return unique[:limit]


__all__ = ["router"]
