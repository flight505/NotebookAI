"""Lint router: POST /lint, GET /findings, POST /findings/{id}/resolve."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from ulid import ULID

from notebookai.agent import operations as agent_operations
from notebookai.agent.runtime import AgentRuntime
from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    get_runtime,
    resolve_notebook_root,
)
from notebookai.api.sse import broadcaster
from notebookai.index.schema import LintFinding
from notebookai.index.store import IndexStore

router = APIRouter(prefix="/notebooks/{notebook_id}/lint", tags=["lint"])


class LintRequest(BaseModel):
    mode: Literal["light", "full"] = "light"


class LintAccepted(BaseModel):
    op_id: str
    notebook_id: str


class LintFindingOut(BaseModel):
    id: str
    notebook_id: str
    kind: str
    status: str
    payload: dict[str, Any] | None = None


def _store(notebook_root: Path) -> IndexStore:
    s = IndexStore(notebook_root)
    s.bootstrap()
    return s


async def _drive_lint(
    runtime: AgentRuntime,
    notebook_root: Path,
    notebook_id: str,
    op_id: str,
    *,
    mode: Literal["light", "full"],
) -> None:
    try:
        result = await agent_operations.lint(runtime, notebook_root, mode=mode)
    except Exception as exc:  # noqa: BLE001
        broadcaster.publish(
            notebook_id,
            {
                "_event_name": "agent.error",
                "notebook_id": notebook_id,
                "op_id": op_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "retriable": False,
            },
        )
        return
    for ev in result.events:
        broadcaster.publish(notebook_id, ev)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=LintAccepted)
async def trigger_lint(
    notebook_id: str,
    body: LintRequest,
    config: Annotated[AppConfig, Depends(get_config)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> LintAccepted:
    root = resolve_notebook_root(notebook_id, config)
    op_id = str(ULID())
    asyncio.create_task(_drive_lint(runtime, root, notebook_id, op_id, mode=body.mode))
    return LintAccepted(op_id=op_id, notebook_id=notebook_id)


@router.get("/findings", response_model=list[LintFindingOut])
def list_findings(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[LintFindingOut]:
    root = resolve_notebook_root(notebook_id, config)
    store = _store(root)
    try:
        with store.session() as s:
            q = select(LintFinding).where(LintFinding.notebook_id == notebook_id)
            if status_filter:
                q = q.where(LintFinding.status == status_filter)
            rows = s.scalars(q).all()
            out = [
                LintFindingOut(
                    id=r.id,
                    notebook_id=r.notebook_id,
                    kind=r.kind,
                    status=r.status,
                    payload=r.payload,
                )
                for r in rows
            ]
    finally:
        store.close()
    return out


@router.post("/findings/{finding_id}/resolve", response_model=LintFindingOut)
def resolve_finding(
    notebook_id: str,
    finding_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> LintFindingOut:
    root = resolve_notebook_root(notebook_id, config)
    store = _store(root)
    try:
        with store.session() as s:
            row = s.get(LintFinding, finding_id)
            if row is None or row.notebook_id != notebook_id:
                raise HTTPException(status_code=404, detail="finding not found")
            row.status = "resolved"
            return LintFindingOut(
                id=row.id,
                notebook_id=row.notebook_id,
                kind=row.kind,
                status=row.status,
                payload=row.payload,
            )
    finally:
        store.close()


__all__ = ["router"]
