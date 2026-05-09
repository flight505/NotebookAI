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

Resilience: every published event is assigned a stable ULID at publish time
and stored in a per-notebook ring buffer (``_recent``, capped at
``_RECENT_RING_SIZE``). Reconnecting clients can pass ``Last-Event-ID`` via
the standard SSE header; ``subscribe_envelopes`` will replay any buffered
events newer than that ID before live-tailing. When a slow consumer's queue
is full, the broadcaster drops one in-flight event and inserts a synthetic
:class:`StreamGap` so the client knows to refetch authoritative state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, ClassVar

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

# Max retained envelopes per notebook for Last-Event-ID replay. Sized to cover
# the typical reconnect window (a few seconds of UI burst) without bloating
# memory: 128 envelopes × ~1KB payload preview = ~128KB per active notebook.
_RECENT_RING_SIZE = 128

_INDEX_EVENT_FILE_CHANGED = "file.changed"


@dataclass(frozen=True, slots=True)
class StreamGap:
    """Synthetic event signalling that one or more events were dropped.

    Emitted into a slow subscriber's queue when a publish would otherwise
    overflow. The frontend's SSE consumer should treat this as "your local
    state may be stale" and re-fetch authoritative views (article tree,
    findings, scheduler status, …) rather than relying on the next live
    event. The dropped event id is informational; the client typically just
    uses receipt of stream.gap as the trigger.
    """

    notebook_id: str
    dropped_event_id: str | None = None
    _event_name: ClassVar[str] = "stream.gap"

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "dropped_event_id": self.dropped_event_id,
        }


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


def event_to_sse(event_id: str | None, event: Any) -> str:
    """Format an event as an SSE frame.

    The ``event_id`` should be the canonical ID assigned at publish time so
    reconnecting clients can use it as ``Last-Event-ID``. ``None`` is
    accepted for ad-hoc one-shot streams (ask mode) where reconnect-replay
    isn't meaningful; a fresh ULID is allocated in that case.
    """
    name = _event_name(event)
    payload = _event_payload(event)
    eid = event_id or str(ULID())
    return f"id: {eid}\nevent: {name}\ndata: {json.dumps(payload, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Per-notebook broadcaster
# ---------------------------------------------------------------------------


class EventBroadcaster:
    """In-process pub/sub keyed by notebook id.

    Per-notebook state:

    * ``_channels`` — list of subscriber queues. Each queue carries
      :class:`_Envelope` items (event_id + event), plus the disconnect
      sentinel. The legacy :meth:`subscribe` API unwraps to bare events
      so existing callers (ask router, scheduler tests) keep working.
    * ``_recent`` — a ring buffer of the last :data:`_RECENT_RING_SIZE`
      envelopes published, for ``Last-Event-ID`` replay on reconnect.

    On :class:`asyncio.QueueFull`, one in-flight envelope is sacrificed and
    a :class:`StreamGap` envelope is inserted so the slow consumer learns
    its local view is stale and can refetch.
    """

    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue]] = {}
        self._loops: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._recent: dict[str, deque[_Envelope]] = {}

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
        """Yield raw events for the given notebook until cancelled.

        Legacy interface — does NOT support ``Last-Event-ID`` replay because
        it discards the canonical event id. Use :meth:`subscribe_envelopes`
        for SSE responses where reconnect resilience matters.
        """
        async for env in self.subscribe_envelopes(notebook_id):
            yield env.event

    async def subscribe_envelopes(
        self,
        notebook_id: str,
        *,
        last_event_id: str | None = None,
    ) -> AsyncIterator[_Envelope]:
        """Yield :class:`_Envelope` items (event_id + event) until cancelled.

        If ``last_event_id`` is provided, any envelopes in the ring buffer
        whose id is strictly greater (ULIDs sort lexicographically by time)
        are emitted before the live tail. This lets a reconnecting client
        recover events it missed during the disconnect window without
        forcing a full state refetch.
        """
        # Replay phase — drain anything newer than last_event_id from the
        # ring buffer. Snapshotted up-front so concurrent publishes during
        # iteration don't cause us to skip live events later.
        if last_event_id:
            replay = [
                env
                for env in tuple(self._recent.get(notebook_id) or ())
                if env.event_id > last_event_id
            ]
            for env in replay:
                yield env

        q = await self._add_subscriber(notebook_id)
        try:
            while True:
                item = await q.get()
                if item is _SENTINEL_DISCONNECT:
                    return
                # Defensive: legacy publishers (or pre-refactor tests) might
                # push a bare event. Wrap on the fly so the subscribe contract
                # stays consistent.
                if isinstance(item, _Envelope):
                    yield item
                else:
                    yield _Envelope(event_id=str(ULID()), event=item)
        finally:
            await self._remove_subscriber(notebook_id, q)

    def publish(self, notebook_id: str, event: Any) -> str:
        """Publish an event; return the canonical event id assigned to it.

        Safe to call from any thread: cross-thread delivery is routed via
        ``loop.call_soon_threadsafe`` so the asyncio.Queue's awaiter wakes up.

        Backpressure: when a subscriber's queue is full, one buffered
        envelope is dropped and replaced with a :class:`StreamGap` so the
        slow client knows it lost data.
        """
        envelope = _Envelope(event_id=str(ULID()), event=event)
        ring = self._recent.setdefault(
            notebook_id, deque(maxlen=_RECENT_RING_SIZE)
        )
        ring.append(envelope)

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
                    target_loop.call_soon_threadsafe(
                        _safe_put_envelope, q, envelope, notebook_id
                    )
                except RuntimeError:
                    # loop is closed — drop the subscriber lazily on next pass.
                    continue
                continue
            _safe_put_envelope(q, envelope, notebook_id)
        return envelope.event_id

    async def close_subscribers(self, notebook_id: str) -> None:
        """Send disconnect sentinel to all subscribers of a notebook."""
        queues = list(self._channels.get(notebook_id) or ())
        for q in queues:
            try:
                q.put_nowait(_SENTINEL_DISCONNECT)
            except Exception:  # noqa: BLE001
                continue

    async def close_all_subscribers(self) -> None:
        """Disconnect every active subscriber on every channel.

        Called from the FastAPI lifespan exit so an SSE client that is mid-
        stream gets a clean EOF instead of a connection reset on shutdown.
        """
        for notebook_id in list(self._channels.keys()):
            await self.close_subscribers(notebook_id)


_SENTINEL_DISCONNECT = object()


@dataclass(frozen=True, slots=True)
class _Envelope:
    """Internal carrier of (event_id, event) tuples through subscriber queues
    so the canonical id assigned at publish time survives all the way to the
    SSE wire format."""

    event_id: str
    event: Any
    # Track whether we've already inserted a gap marker for this overflow so
    # a tight burst of QueueFull errors doesn't spam the client.
    _is_gap_marker: bool = field(default=False)


def _safe_put_envelope(
    q: asyncio.Queue, envelope: _Envelope, notebook_id: str
) -> None:
    """Put with backpressure handling: on QueueFull, drop the oldest buffered
    envelope and insert a StreamGap before retrying. Never raises."""
    try:
        q.put_nowait(envelope)
        return
    except asyncio.QueueFull:
        pass
    except RuntimeError:
        return
    except Exception:  # noqa: BLE001
        return

    # Make room — discard the oldest buffered envelope for this subscriber.
    dropped_id: str | None = None
    try:
        dropped = q.get_nowait()
        if isinstance(dropped, _Envelope):
            dropped_id = dropped.event_id
    except (asyncio.QueueEmpty, Exception):  # noqa: BLE001
        pass

    log.warning(
        "broadcaster_queue_full",
        extra={"notebook_id": notebook_id, "dropped_event_id": dropped_id},
    )

    gap = _Envelope(
        event_id=str(ULID()),
        event=StreamGap(notebook_id=notebook_id, dropped_event_id=dropped_id),
        _is_gap_marker=True,
    )
    for item in (gap, envelope):
        try:
            q.put_nowait(item)
        except (asyncio.QueueFull, Exception):  # noqa: BLE001
            # If we still can't fit, give up — the gap event itself signals
            # the client to refetch, which is enough.
            return


broadcaster = EventBroadcaster()


# ---------------------------------------------------------------------------
# StreamingResponse wrapping
# ---------------------------------------------------------------------------


def sse_response(generator: AsyncIterator[Any]) -> StreamingResponse:
    """Wrap an async event generator as an SSE StreamingResponse.

    The generator may yield either :class:`_Envelope` items (preferred — the
    canonical event id flows to the wire as ``id:`` for Last-Event-ID
    replay) or bare events (a fresh ULID is allocated per emit). Sends
    ``: keep-alive\\n\\n`` periodically so proxies don't time out.
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
                    if isinstance(result, _Envelope):
                        frame = event_to_sse(result.event_id, result.event)
                    else:
                        frame = event_to_sse(None, result)
                    yield frame.encode("utf-8")
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
