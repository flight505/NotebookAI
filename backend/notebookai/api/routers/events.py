"""SSE events router: GET /api/notebooks/{id}/events."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

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
    request: Request,
    config: Annotated[AppConfig, Depends(get_config)],
    last_event_id: Annotated[
        str | None,
        Header(alias="Last-Event-ID"),
    ] = None,
):
    """Subscribe to a notebook's event channel.

    Honors the standard ``Last-Event-ID`` SSE reconnect header so a client
    that drops momentarily can resume from the buffered ring without losing
    every event in the gap. Falls back to a query-string ``last_event_id``
    parameter for transports (test clients, curl one-shots) that don't set
    the header.
    """
    resolve_notebook_root(notebook_id, config)
    if last_event_id is None:
        last_event_id = request.query_params.get("last_event_id")
    return sse_response(
        broadcaster.subscribe_envelopes(
            notebook_id, last_event_id=last_event_id
        )
    )


__all__ = ["router"]
