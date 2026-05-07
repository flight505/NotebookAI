"""Lint router: POST /lint, GET /findings, POST /findings/{id}/resolve."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from ulid import ULID

from notebookai.agent import operations as agent_operations
from notebookai.agent.budget import BudgetTracker
from notebookai.agent.lint import LintEngine
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
    degraded: bool = False


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
        result = await agent_operations.smart_lint(runtime, notebook_root, mode=mode)
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
    degraded = not runtime.credentials_available()
    asyncio.create_task(_drive_lint(runtime, root, notebook_id, op_id, mode=body.mode))
    return LintAccepted(
        op_id=op_id, notebook_id=notebook_id, degraded=degraded
    )


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


class ResolveBody(BaseModel):
    action: Literal["accept", "reject"]


@router.post("/findings/{finding_id}/resolve", response_model=LintFindingOut)
async def resolve_finding(
    notebook_id: str,
    finding_id: str,
    body: ResolveBody,
    config: Annotated[AppConfig, Depends(get_config)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> LintFindingOut:
    root = resolve_notebook_root(notebook_id, config)
    store = _store(root)
    try:
        if body.action == "reject":
            with store.session() as s:
                row = s.get(LintFinding, finding_id)
                if row is None or row.notebook_id != notebook_id:
                    raise HTTPException(status_code=404, detail="finding not found")
                row.status = "rejected"
                return LintFindingOut(
                    id=row.id,
                    notebook_id=row.notebook_id,
                    kind=row.kind,
                    status=row.status,
                    payload=row.payload,
                )

        # action == "accept" — apply via LintEngine.
        with store.session() as s:
            existing = s.get(LintFinding, finding_id)
            if existing is None or existing.notebook_id != notebook_id:
                raise HTTPException(status_code=404, detail="finding not found")

        engine = LintEngine(runtime, store, notebook_id)
        try:
            await engine.apply_finding(finding_id, root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with store.session() as s:
            row = s.get(LintFinding, finding_id)
            if row is None:
                raise HTTPException(status_code=404, detail="finding not found")
            return LintFindingOut(
                id=row.id,
                notebook_id=row.notebook_id,
                kind=row.kind,
                status=row.status,
                payload=row.payload,
            )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Budget endpoints
# ---------------------------------------------------------------------------


class BudgetOut(BaseModel):
    notebook_id: str
    day: date
    input_tokens_used: int
    output_tokens_used: int
    input_limit: int
    output_limit: int
    last_op_at: datetime | None = None
    denied_op_count: int


class BudgetUpdate(BaseModel):
    input_limit: int | None = Field(default=None, ge=0)
    output_limit: int | None = Field(default=None, ge=0)


def _budget_tracker(notebook_id: str, root: Path) -> tuple[BudgetTracker, IndexStore, dict]:
    meta_path = root / ".notebookai" / "notebook.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    agent_cfg = (meta.get("agent") or {}) if isinstance(meta, dict) else {}
    daily = int(agent_cfg.get("lint_budget_tokens_per_day", 50_000))
    output_limit = int(agent_cfg.get("lint_output_budget_tokens_per_day", 10_000))
    store = _store(root)
    return BudgetTracker(store, notebook_id, input_limit=daily, output_limit=output_limit), store, meta


@router.get("/budget", response_model=BudgetOut)
def read_budget(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> BudgetOut:
    root = resolve_notebook_root(notebook_id, config)
    tracker, store, _meta = _budget_tracker(notebook_id, root)
    try:
        snap = tracker.get_today()
        return BudgetOut(**snap.model_dump())
    finally:
        store.close()


@router.post("/budget", response_model=BudgetOut)
def update_budget(
    notebook_id: str,
    body: BudgetUpdate,
    config: Annotated[AppConfig, Depends(get_config)],
) -> BudgetOut:
    root = resolve_notebook_root(notebook_id, config)
    tracker, store, meta = _budget_tracker(notebook_id, root)
    try:
        snap = tracker.update_limits(
            input_limit=body.input_limit,
            output_limit=body.output_limit,
        )
        # Persist into notebook.json so future processes see the new limits.
        if not isinstance(meta, dict):
            meta = {}
        agent_cfg = dict(meta.get("agent") or {})
        if body.input_limit is not None:
            agent_cfg["lint_budget_tokens_per_day"] = int(body.input_limit)
        if body.output_limit is not None:
            agent_cfg["lint_output_budget_tokens_per_day"] = int(body.output_limit)
        meta["agent"] = agent_cfg
        meta_path = root / ".notebookai" / "notebook.json"
        try:
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        return BudgetOut(**snap.model_dump())
    finally:
        store.close()


__all__ = ["router"]
