"""History router — git log / show via :class:`NotebookRepo`.

Mirrors `/api/notebooks/{id}/log` semantics in disabled-git mode by
reading ``.notebookai/oplog.jsonl``.
"""

from __future__ import annotations

import subprocess
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    resolve_notebook_root,
)
from notebookai.git import Commit, NotebookRepo

router = APIRouter(prefix="/notebooks/{notebook_id}/history", tags=["history"])


class HistoryEntry(BaseModel):
    sha: str
    author: str | None = None
    created_at: str | None = None
    subject: str
    body: str = ""
    op: str | None = None
    op_id: str | None = None
    files_changed: list[str] = []
    insertions: int = 0
    deletions: int = 0


class HistoryDetail(HistoryEntry):
    diff: str = ""


def _commit_to_entry(c: Commit) -> HistoryEntry:
    author = c.author_name or None
    if author and c.author_email:
        author = f"{c.author_name} <{c.author_email}>"
    return HistoryEntry(
        sha=c.sha,
        author=author,
        created_at=c.created_at or None,
        subject=c.subject,
        body=c.body,
        op=c.op,
        op_id=c.op_id,
        files_changed=list(c.files_changed),
        insertions=c.insertions,
        deletions=c.deletions,
    )


@router.get("", response_model=list[HistoryEntry])
def list_history(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    since_sha: Annotated[str | None, Query()] = None,
    op: Annotated[str | None, Query()] = None,
) -> list[HistoryEntry]:
    root = resolve_notebook_root(notebook_id, config)
    repo = NotebookRepo(root)
    commits = repo.get_history(limit=limit, since_sha=since_sha, op_filter=op)
    return [_commit_to_entry(c) for c in commits]


@router.get("/{sha}", response_model=HistoryDetail)
def get_history_entry(
    notebook_id: str,
    sha: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> HistoryDetail:
    root = resolve_notebook_root(notebook_id, config)
    repo = NotebookRepo(root)
    c = repo.get_commit(sha)
    if c is None:
        raise HTTPException(status_code=404, detail="commit not found")
    base = _commit_to_entry(c)
    diff = ""
    if repo.is_enabled():
        try:
            out = subprocess.run(
                ["git", "show", "--stat", "--pretty=fuller", sha],
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            diff = out.stdout or ""
        except (subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(status_code=500, detail=f"git show failed: {exc}") from exc
    return HistoryDetail(**base.model_dump(), diff=diff)


@router.post("/{sha}/revert", response_model=HistoryDetail)
def revert_history_entry(
    notebook_id: str,
    sha: str,
    config: Annotated[AppConfig, Depends(get_config)],
    x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
) -> HistoryDetail:
    if (x_confirm or "").lower() != "revert":
        raise HTTPException(
            status_code=400,
            detail="missing X-Confirm: revert header",
        )
    root = resolve_notebook_root(notebook_id, config)
    repo = NotebookRepo(root)
    if not repo.is_enabled():
        raise HTTPException(
            status_code=400,
            detail="revert unavailable: git is disabled for this notebook",
        )
    try:
        new_sha = repo.revert_op(sha)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"revert failed: {(exc.stderr or '')[:300]}",
        ) from exc
    c = repo.get_commit(new_sha)
    if c is None:
        raise HTTPException(status_code=500, detail="revert produced no commit")
    return HistoryDetail(**_commit_to_entry(c).model_dump(), diff="")


__all__ = ["router"]
