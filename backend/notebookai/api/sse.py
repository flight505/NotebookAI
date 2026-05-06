"""Per-notebook event broadcaster + SSE wire format helpers.

Wire format (per CONTRACTS.md § SSE event types):

    id: <ulid>
    event: <name>
    data: <json>

Events come from three producers:

* ``notebookai.agent.events`` — agent.tool_call/tool_result/message/done/error.
* ``notebookai.index.events`` — file watcher events; emitted as ``file.changed``.
* Phase 10/11 producers — ``commit.created`` and ``lint.finding`` are
  forwarded as bare dicts via :func:`broadcaster.publish`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi.responses import StreamingResponse
from ulid import ULID

from notebookai.agent.events import (
    AgentDone,
    AgentError,
    AgentMessage,
    AgentToolCall,
    AgentToolResult,
)

log = logging.getLogger(__name__)


KEEPALIVE_INTERVAL_S = 15.0

_INDEX_EVENT_FILE_CHANGED = "file.changed"


def _event_name(event: Any) -> str:
    """Resolve the SSE event name for an event object."""
    name = getattr(event, "_event_name", None)
    if isinstance(name, str) and name:
        return name
    # Index events live under notebookai.index.events; their names are
    # things like "raw.added", "wiki.modified" etc. We surface them under
    # the umbrella ``file.changed`` SSE name (per CONTRACTS § events router).
    if event.__class__.__module__.startswith("notebookai.index."):
        return _INDEX_EVENT_FILE_CHANGED
    return event.__class__.__name__.lower()


def _event_payload(event: Any) -> dict[str, Any]:
    """Serialise an event to a JSON-compatible dict."""
    if hasattr(event, "to_dict") and callable(event.to_dict):
        try:
            return dict(event.to_dict())
        except Exception:  # noqa: BLE001
            pass
    if isinstance(event, dict):
        return dict(event)
    if is_dataclass(event):
        # asdict on frozen slotted dataclasses works fine.
        d = asdict(event)
        # For index events, normalize fields so the SSE shape matches contracts.
        if event.__class__.__module__.startswith("notebookai.index."):
            cls_name = event.__class__.__name__  # e.g. "WikiAdded"
            scope = ""
            kind = ""
            if cls_name.startswith("Raw"):
                scope = "raw"
            elif cls_name.startswith("Wiki"):
                scope = "wiki"
            elif cls_name.startswith("Chats"):
                scope = "chats"
            elif cls_name == "IndexDirty":
                scope = "meta"
            for suffix, k in (("Added", "added"), ("Modified", "modified"), ("Deleted", "deleted")):
                if cls_name.endswith(suffix):
                    kind = k
                    break
            d.setdefault("scope", scope)
            if kind:
                d.setdefault("kind", kind)
        return d
    # Fallback: best-effort __dict__ snapshot.
    return {k: v for k, v in getattr(event, "__dict__", {}).items() if not k.startswith("_")}


def event_to_sse(event: Any) -> str:
    """Format any supported event as an SSE frame."""
    name = _event_name(event)
    payload = _event_payload(event)
    eid = str(ULID())
    return f"id: {eid}\nevent: {name}\ndata: {json.dumps(payload, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Per-notebook broadcaster
# ---------------------------------------------------------------------------


class EventBroadcaster:
    """In-process pub/sub keyed by notebook id.

    Each subscribe() returns an async iterator of events for one client. The
    broadcaster keeps a list of asyncio.Queue per notebook; full / closed
    queues are dropped on the next publish().
    """

    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue]] = {}
        self._loops: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}

    async def _add_subscriber(self, notebook_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._channels.setdefault(notebook_id, []).append(q)
        try:
            self._loops[q] = asyncio.get_running_loop()
        except RuntimeError:
            pass
        return q

    async def _remove_subscriber(self, notebook_id: str, q: asyncio.Queue) -> None:
        queues = self._channels.get(notebook_id) or []
        try:
            queues.remove(q)
        except ValueError:
            pass
        self._loops.pop(q, None)
        if not queues:
            self._channels.pop(notebook_id, None)

    async def subscribe(self, notebook_id: str) -> AsyncIterator[Any]:
        """Yield events for the given notebook until cancelled."""
        q = await self._add_subscriber(notebook_id)
        try:
            while True:
                event = await q.get()
                if event is _SENTINEL_DISCONNECT:
                    return
                yield event
        finally:
            await self._remove_subscriber(notebook_id, q)

    def publish(self, notebook_id: str, event: Any) -> None:
        """Publish an event to all current subscribers (best-effort).

        Safe to call from any thread: cross-thread delivery is routed via
        ``loop.call_soon_threadsafe`` so the asyncio.Queue's awaiter wakes up.
        """
        queues = list(self._channels.get(notebook_id) or ())
        for q in queues:
            target_loop = self._loops.get(q)
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if target_loop is not None and target_loop is not running:
                # Cross-thread: schedule on the subscriber's loop.
                try:
                    target_loop.call_soon_threadsafe(_safe_put_nowait, q, event)
                except RuntimeError:
                    # loop is closed — drop the subscriber lazily on next pass.
                    continue
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("broadcaster_queue_full", extra={"notebook_id": notebook_id})
            except Exception:  # noqa: BLE001
                continue

    async def close_subscribers(self, notebook_id: str) -> None:
        """Send disconnect sentinel to all subscribers of a notebook."""
        queues = list(self._channels.get(notebook_id) or ())
        for q in queues:
            try:
                q.put_nowait(_SENTINEL_DISCONNECT)
            except Exception:  # noqa: BLE001
                continue


_SENTINEL_DISCONNECT = object()


def _safe_put_nowait(q: asyncio.Queue, event: Any) -> None:
    try:
        q.put_nowait(event)
    except (asyncio.QueueFull, RuntimeError):
        pass


broadcaster = EventBroadcaster()


# ---------------------------------------------------------------------------
# StreamingResponse wrapping
# ---------------------------------------------------------------------------


def sse_response(generator: AsyncIterator[Any]) -> StreamingResponse:
    """Wrap an async event generator as an SSE StreamingResponse.

    Sends ``: keep-alive\\n\\n`` periodically so proxies don't time out.
    """

    async def _stream() -> AsyncIterator[bytes]:
        # Yield an initial comment line so headers flush immediately.
        yield b": ready\n\n"
        next_event_task: asyncio.Task | None = asyncio.ensure_future(generator.__anext__())
        keepalive_task: asyncio.Task = asyncio.ensure_future(asyncio.sleep(KEEPALIVE_INTERVAL_S))
        try:
            while True:
                pending = {t for t in (next_event_task, keepalive_task) if t is not None}
                if not pending:
                    break
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if next_event_task is not None and next_event_task in done:
                    try:
                        result = next_event_task.result()
                    except StopAsyncIteration:
                        next_event_task = None
                        break
                    yield event_to_sse(result).encode("utf-8")
                    next_event_task = asyncio.ensure_future(generator.__anext__())
                if keepalive_task in done:
                    yield b": keep-alive\n\n"
                    keepalive_task = asyncio.ensure_future(
                        asyncio.sleep(KEEPALIVE_INTERVAL_S)
                    )
        finally:
            for t in (next_event_task, keepalive_task):
                if t is not None and not t.done():
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
            aclose = getattr(generator, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception:  # noqa: BLE001
                    pass

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Re-export agent event classes for convenience in routers.
__all__ = [
    "EventBroadcaster",
    "broadcaster",
    "event_to_sse",
    "sse_response",
    "AgentDone",
    "AgentError",
    "AgentMessage",
    "AgentToolCall",
    "AgentToolResult",
]
