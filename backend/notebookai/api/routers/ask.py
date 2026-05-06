"""Ask router: POST /api/notebooks/{id}/ask (sync + SSE)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from notebookai.agent import operations as agent_operations
from notebookai.agent.runtime import AgentRuntime
from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    get_runtime,
    resolve_notebook_root,
)
from notebookai.api.sse import broadcaster, sse_response

router = APIRouter(prefix="/notebooks/{notebook_id}/ask", tags=["ask"])


class AskRequest(BaseModel):
    prompt: str = Field(min_length=1)
    archive: bool = False
    stream: bool = False


class AskResponse(BaseModel):
    op_id: str
    answer: str
    citations: list[dict[str, Any]] = []
    commit_sha: str | None = None
    usage: dict[str, Any] = {}


async def _ask_event_stream(
    runtime: AgentRuntime,
    notebook_root: Path,
    notebook_id: str,
    *,
    prompt: str,
    archive: bool,
) -> AsyncIterator[Any]:
    """Run query() and yield its events as they accumulate.

    Implementation note: ``operations.query`` aggregates events into the
    OperationResult before returning. Rather than wait for completion, we
    subscribe the broadcaster, kick off the op, and forward events as they
    pass through. This is the SSE shape the frontend will consume.
    """

    async def _drive() -> None:
        try:
            result = await agent_operations.query(
                runtime,
                notebook_root,
                prompt=prompt,
                archive=archive,
            )
        except Exception as exc:  # noqa: BLE001
            broadcaster.publish(
                notebook_id,
                {
                    "_event_name": "agent.error",
                    "notebook_id": notebook_id,
                    "op_id": "",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "retriable": False,
                },
            )
            return
        # After completion replay any events the broadcaster missed (the
        # runtime publishes during streaming once Phase 8b wires the bridge).
        for ev in result.events:
            broadcaster.publish(notebook_id, ev)

    task = asyncio.create_task(_drive())
    try:
        async for event in broadcaster.subscribe(notebook_id):
            yield event
            # Stop after a terminal event for this op.
            name = getattr(event, "_event_name", "")
            if name in {"agent.done", "agent.error"}:
                break
    finally:
        if not task.done():
            # Don't cancel — let the op finish in the background.
            pass


@router.post("")
async def ask(
    notebook_id: str,
    body: AskRequest,
    config: Annotated[AppConfig, Depends(get_config)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
):
    root = resolve_notebook_root(notebook_id, config)

    if body.stream:
        gen = _ask_event_stream(
            runtime,
            root,
            notebook_id,
            prompt=body.prompt,
            archive=body.archive,
        )
        return sse_response(gen)

    result = await agent_operations.query(
        runtime,
        root,
        prompt=body.prompt,
        archive=body.archive,
    )
    return AskResponse(
        op_id=result.op_id,
        answer=result.summary,
        citations=[],
        commit_sha=result.commit_sha,
        usage=dict(result.usage or {}),
    )


__all__ = ["router"]
