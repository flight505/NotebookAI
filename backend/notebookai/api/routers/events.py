"""SSE events router: GET /api/notebooks/{id}/events."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    resolve_notebook_root,
)
from notebookai.api.sse import broadcaster, sse_response

router = APIRouter(prefix="/notebooks/{notebook_id}/events", tags=["events"])


@router.get("")
async def stream_events(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
):
    # Resolve notebook root just to enforce existence (returns 404 otherwise).
    resolve_notebook_root(notebook_id, config)
    return sse_response(broadcaster.subscribe(notebook_id))


__all__ = ["router"]
