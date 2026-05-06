"""Ingest router: POST /ingest and POST /ingest/file.

Spawns the agent ingest op as a background task. Events are forwarded
through the singleton :data:`broadcaster`.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
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

router = APIRouter(prefix="/notebooks/{notebook_id}/ingest", tags=["ingest"])


SourceType = Literal["url", "pdf", "youtube"]


class IngestRequest(BaseModel):
    source: str = Field(min_length=1)
    source_type: SourceType | None = None
    topic_hint: str | None = None


class IngestAccepted(BaseModel):
    op_id: str
    notebook_id: str


async def _drive_ingest(
    runtime: AgentRuntime,
    notebook_root: Path,
    notebook_id: str,
    op_id: str,
    *,
    source: str,
    source_type: SourceType | None,
) -> None:
    """Run the agent ingest op and republish its events on the broadcaster."""
    try:
        result = await agent_operations.ingest(
            runtime,
            notebook_root,
            source=source,
            source_type=source_type,
        )
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


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=IngestAccepted)
async def ingest_source(
    notebook_id: str,
    body: IngestRequest,
    config: Annotated[AppConfig, Depends(get_config)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> IngestAccepted:
    root = resolve_notebook_root(notebook_id, config)
    op_id = str(ULID())

    asyncio.create_task(
        _drive_ingest(
            runtime,
            root,
            notebook_id,
            op_id,
            source=body.source,
            source_type=body.source_type,
        )
    )
    return IngestAccepted(op_id=op_id, notebook_id=notebook_id)


@router.post(
    "/file", status_code=status.HTTP_202_ACCEPTED, response_model=IngestAccepted
)
async def ingest_file(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    file: Annotated[UploadFile, File(...)],
    topic_hint: Annotated[str | None, Form()] = None,
) -> IngestAccepted:
    root = resolve_notebook_root(notebook_id, config)

    # Save upload to a temp file (ingest op reads source path).
    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    fd, tmp_path = tempfile.mkstemp(prefix="notebookai-upload-", suffix=suffix)
    try:
        import os

        with os.fdopen(fd, "wb") as fh:
            shutil.copyfileobj(file.file, fh)
    except Exception as exc:  # noqa: BLE001
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"upload failed: {exc}") from exc

    op_id = str(ULID())
    asyncio.create_task(
        _drive_ingest(
            runtime,
            root,
            notebook_id,
            op_id,
            source=tmp_path,
            source_type="pdf",
        )
    )
    _ = topic_hint  # accepted but currently unused (forwarded to adapters in a later phase)
    return IngestAccepted(op_id=op_id, notebook_id=notebook_id)


__all__ = ["router"]
