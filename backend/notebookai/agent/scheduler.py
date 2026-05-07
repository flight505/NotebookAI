"""Per-notebook lint scheduler.

Each notebook gets at most one ``asyncio.Task`` (spawned lazily) that loops
forever inside the FastAPI process. On each tick the loop:

1. Picks idle vs run via cheap mtime sniff over ``wiki/**/*.md`` + ``raw/**``.
2. Asks :class:`BudgetTracker` whether a Haiku call would fit. If not, skips.
3. Drives :func:`smart_lint` — degraded mode automatically skips Haiku.
4. Publishes ``lint.scheduled`` / ``lint.skipped`` / ``lint.run_complete``
   events to the SSE broadcaster.

The loop uses ``time.monotonic()`` for interval math; ``time.time()`` only
shows up in human-facing timestamps.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel
from ulid import ULID

from notebookai.agent import operations as agent_operations
from notebookai.agent.budget import BudgetTracker
from notebookai.agent.events import (
    AgentDone,
    AgentUnavailable,
    LintRunComplete,
    LintScheduled,
    LintSkipped,
)
from notebookai.agent.runtime import AgentRuntime
from notebookai.index.store import IndexStore


def _broadcaster():
    """Lazy lookup of the SSE broadcaster.

    Avoids a top-level import cycle: the lint router imports the scheduler,
    so the scheduler cannot import the api package at module load.
    """
    from notebookai.api.sse import broadcaster as _b

    return _b

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class SchedulerStatus(BaseModel):
    """Snapshot returned to the API surface."""

    notebook_id: str
    enabled: bool
    interval_minutes: int
    last_run_at: float | None = None  # unix seconds (time.time())
    next_run_at: float | None = None  # unix seconds; None when disabled
    last_result: Literal["ran", "skipped", "error"] | None = None
    last_skip_reason: str | None = None
    last_finding_count: int | None = None
    idle: bool = False
    running: bool = False


# ---------------------------------------------------------------------------
# Internal per-notebook bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class _NotebookState:
    interval_minutes: int = 60
    enabled: bool = True
    last_run_monotonic: float | None = None
    last_run_at: float | None = None
    last_seen_mtime: float = 0.0
    last_result: Literal["ran", "skipped", "error"] | None = None
    last_skip_reason: str | None = None
    last_finding_count: int | None = None
    task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    trigger_event: asyncio.Event = field(default_factory=asyncio.Event)
    trigger_pending: bool = False
    last_trigger_monotonic: float = 0.0


_TRIGGER_DEBOUNCE_S = 0.1

# Plus/minus jitter applied to every scheduled-tick sleep so N notebooks
# don't all wake on the same boundary. ±10% spreads the herd far enough to
# de-cluster the per-tick BudgetTracker / Haiku call without meaningfully
# changing the user-perceived cadence.
_JITTER_FRACTION = 0.1


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class LintScheduler:
    """In-process scheduler driving :func:`smart_lint` per-notebook.

    The scheduler does NOT scan the library on startup; instead it lazily
    spawns a Task the first time it sees a notebook (via ``trigger_now`` or
    ``status``). This keeps boot cheap and avoids touching notebooks the
    user never opens this session.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        library_root: Path,
        *,
        default_interval_minutes: int = 60,
    ) -> None:
        self.runtime = runtime
        self.library_root = Path(library_root)
        self.default_interval_minutes = int(default_interval_minutes)
        self._states: dict[str, _NotebookState] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._stopped = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Mark the scheduler as live; tasks are spawned lazily."""
        if self._started:
            return
        self._started = True
        self._stopped = False
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        log.info("lint_scheduler_started", default_interval_minutes=self.default_interval_minutes)

    def stop(self) -> None:
        """Cancel all running per-notebook tasks."""
        self._stopped = True
        for st in list(self._states.values()):
            t = st.task
            if t is not None and not t.done():
                t.cancel()
        log.info("lint_scheduler_stopped")

    # ------------------------------------------------------------------
    # Notebook resolution
    # ------------------------------------------------------------------
    def _resolve_root(self, notebook_id: str) -> Path | None:
        # Library root only — extra roots are out of scope for the scheduler
        # (and not threaded through here). This matches the per-process
        # default install topology.
        candidate = (self.library_root / notebook_id).resolve()
        if candidate.is_dir() and (candidate / ".notebookai" / "notebook.json").is_file():
            return candidate
        return None

    def _read_meta(self, notebook_root: Path) -> dict[str, Any]:
        meta_path = notebook_root / ".notebookai" / "notebook.json"
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _agent_cfg(self, meta: dict[str, Any]) -> dict[str, Any]:
        agent = meta.get("agent") if isinstance(meta, dict) else None
        return agent if isinstance(agent, dict) else {}

    def _refresh_state_from_meta(self, state: _NotebookState, meta: dict[str, Any]) -> None:
        cfg = self._agent_cfg(meta)
        state.enabled = bool(cfg.get("lint_schedule_enabled", True))
        try:
            interval = int(cfg.get("lint_schedule_interval_minutes", self.default_interval_minutes))
        except (TypeError, ValueError):
            interval = self.default_interval_minutes
        state.interval_minutes = max(1, interval)

    def _ensure_state(self, notebook_id: str) -> _NotebookState:
        st = self._states.get(notebook_id)
        if st is None:
            st = _NotebookState(interval_minutes=self.default_interval_minutes)
            self._states[notebook_id] = st
        return st

    def _ensure_task(self, notebook_id: str) -> _NotebookState | None:
        if not self._started or self._stopped:
            return None
        root = self._resolve_root(notebook_id)
        if root is None:
            return None
        st = self._ensure_state(notebook_id)
        meta = self._read_meta(root)
        self._refresh_state_from_meta(st, meta)
        if st.task is None or st.task.done():
            try:
                loop = self._loop or asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is None:
                # No running loop yet; defer spawning until one is available.
                return st
            st.task = loop.create_task(
                self._per_notebook_loop(notebook_id, root),
                name=f"lint-scheduler-{notebook_id}",
            )
        return st

    # ------------------------------------------------------------------
    # API surface
    # ------------------------------------------------------------------
    def status(self, notebook_id: str) -> SchedulerStatus:
        st = self._ensure_state(notebook_id)
        root = self._resolve_root(notebook_id)
        if root is not None:
            self._refresh_state_from_meta(st, self._read_meta(root))
        next_run_at: float | None = None
        if st.enabled:
            if st.last_run_at is not None:
                next_run_at = st.last_run_at + st.interval_minutes * 60.0
            else:
                next_run_at = time.time() + st.interval_minutes * 60.0
        idle = False
        if root is not None and st.last_run_monotonic is not None:
            current_mtime = _max_mtime(root)
            idle = current_mtime <= st.last_seen_mtime
        # Lazily spawn task on first status read so the loop runs as soon as
        # something cares about this notebook.
        self._ensure_task(notebook_id)
        return SchedulerStatus(
            notebook_id=notebook_id,
            enabled=st.enabled,
            interval_minutes=st.interval_minutes,
            last_run_at=st.last_run_at,
            next_run_at=next_run_at,
            last_result=st.last_result,
            last_skip_reason=st.last_skip_reason,
            last_finding_count=st.last_finding_count,
            idle=idle,
            running=st.lock.locked(),
        )

    def trigger_now(self, notebook_id: str) -> None:
        """Schedule an immediate run; debounces concurrent triggers."""
        st = self._ensure_state(notebook_id)
        now = time.monotonic()
        if st.trigger_pending and (now - st.last_trigger_monotonic) < _TRIGGER_DEBOUNCE_S:
            return
        st.trigger_pending = True
        st.last_trigger_monotonic = now
        st.trigger_event.set()
        self._ensure_task(notebook_id)

    def update_settings(
        self,
        notebook_id: str,
        *,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
    ) -> SchedulerStatus:
        """Apply new settings (the caller persists notebook.json separately)."""
        st = self._ensure_state(notebook_id)
        if enabled is not None:
            st.enabled = bool(enabled)
        if interval_minutes is not None:
            st.interval_minutes = max(1, int(interval_minutes))
        # Wake the loop so it picks up the new interval immediately.
        st.trigger_event.set()
        self._ensure_task(notebook_id)
        return self.status(notebook_id)

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------
    async def _per_notebook_loop(self, notebook_id: str, root: Path) -> None:
        """Wait, check enabled, check idle, check budget, run."""
        st = self._states[notebook_id]
        log.info(
            "lint_scheduler_loop_started",
            notebook_id=notebook_id,
            interval_minutes=st.interval_minutes,
        )
        try:
            while not self._stopped:
                meta = self._read_meta(root)
                self._refresh_state_from_meta(st, meta)
                base_interval_s = max(1.0, st.interval_minutes * 60.0)
                # ±10% jitter — see _JITTER_FRACTION docstring above.
                jitter = random.uniform(-_JITTER_FRACTION, _JITTER_FRACTION)
                interval_s = base_interval_s * (1.0 + jitter)

                # Wait for either the interval or an explicit trigger.
                trigger_task = asyncio.create_task(st.trigger_event.wait())
                sleep_task = asyncio.create_task(asyncio.sleep(interval_s))
                try:
                    done, _pending = await asyncio.wait(
                        {trigger_task, sleep_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    trigger_task.cancel()
                    sleep_task.cancel()
                    raise
                finally:
                    for t in (trigger_task, sleep_task):
                        if not t.done():
                            t.cancel()

                manual = trigger_task in done and st.trigger_event.is_set()
                if manual:
                    st.trigger_event.clear()
                st.trigger_pending = False

                if self._stopped:
                    break

                # Re-read meta so toggles persisted via the API take effect now.
                meta = self._read_meta(root)
                self._refresh_state_from_meta(st, meta)
                if not st.enabled and not manual:
                    continue

                await self._run_once(
                    notebook_id,
                    root,
                    meta=meta,
                    reason="manual" if manual else "interval",
                )
        except asyncio.CancelledError:
            log.info("lint_scheduler_loop_cancelled", notebook_id=notebook_id)
            raise
        except Exception:  # noqa: BLE001
            log.exception("lint_scheduler_loop_crashed", notebook_id=notebook_id)

    # ------------------------------------------------------------------
    async def _run_once(
        self,
        notebook_id: str,
        root: Path,
        *,
        meta: dict[str, Any],
        reason: Literal["interval", "manual"],
    ) -> None:
        st = self._states[notebook_id]
        op_id = str(ULID())
        scheduled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Concurrency: only one run per notebook at a time.
        if st.lock.locked():
            _broadcaster().publish(
                notebook_id,
                LintSkipped(
                    notebook_id=notebook_id,
                    op_id=op_id,
                    reason="already_running",
                ),
            )
            st.last_result = "skipped"
            st.last_skip_reason = "already_running"
            return

        async with st.lock:
            _broadcaster().publish(
                notebook_id,
                LintScheduled(
                    notebook_id=notebook_id,
                    op_id=op_id,
                    scheduled_at=scheduled_at,
                    reason=reason,
                ),
            )

            current_mtime = _max_mtime(root)
            # Idle check: only relevant for interval ticks. Manual runs always go.
            if (
                reason == "interval"
                and st.last_run_monotonic is not None
                and current_mtime <= st.last_seen_mtime
            ):
                _broadcaster().publish(
                    notebook_id,
                    LintSkipped(
                        notebook_id=notebook_id,
                        op_id=op_id,
                        reason="idle",
                    ),
                )
                st.last_result = "skipped"
                st.last_skip_reason = "idle"
                return

            # Budget check (only meaningful when Claude is actually available).
            credentials_available = self.runtime.credentials_available()
            if credentials_available:
                cfg = self._agent_cfg(meta)
                input_limit = int(cfg.get("lint_budget_tokens_per_day", 50_000))
                output_limit = int(cfg.get("lint_output_budget_tokens_per_day", 10_000))
                store: IndexStore | None = None
                try:
                    store = IndexStore(root)
                    store.bootstrap()
                    bt = BudgetTracker(
                        store,
                        notebook_id,
                        input_limit=input_limit,
                        output_limit=output_limit,
                    )
                    ok, _why = bt.can_spend(estimated_input=4_000, estimated_output=1_000)
                    if not ok:
                        _broadcaster().publish(
                            notebook_id,
                            LintSkipped(
                                notebook_id=notebook_id,
                                op_id=op_id,
                                reason="budget_exhausted",
                            ),
                        )
                        st.last_result = "skipped"
                        st.last_skip_reason = "budget_exhausted"
                        st.last_seen_mtime = current_mtime
                        st.last_run_monotonic = time.monotonic()
                        st.last_run_at = time.time()
                        return
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "lint_scheduler_budget_check_failed",
                        notebook_id=notebook_id,
                        error=str(exc),
                    )
                finally:
                    if store is not None:
                        try:
                            store.close()
                        except Exception:  # noqa: BLE001
                            pass

            # Run the lint dispatcher.
            t0 = time.monotonic()
            mode: Literal["haiku", "passive_only"] = (
                "haiku" if credentials_available else "passive_only"
            )
            finding_count = 0
            tokens_used = 0
            had_findings_in_degraded = False
            try:
                result = await agent_operations.smart_lint(
                    self.runtime, root, mode="light"
                )
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "lint_scheduler_run_failed",
                    notebook_id=notebook_id,
                )
                st.last_result = "error"
                st.last_skip_reason = type(exc).__name__
                # Stamp the run boundaries so we don't tight-loop on errors.
                st.last_seen_mtime = current_mtime
                st.last_run_monotonic = time.monotonic()
                st.last_run_at = time.time()
                return

            # Re-broadcast each result event so the SSE stream sees them
            # (smart_lint collects events into result.events but does not
            # publish them itself when called outside the router).
            for ev in result.events:
                _broadcaster().publish(notebook_id, ev)
                if isinstance(ev, AgentDone):
                    usage = ev.usage or {}
                    in_t = int(usage.get("input_tokens") or 0)
                    out_t = int(usage.get("output_tokens") or 0)
                    tokens_used += in_t + out_t
                    fc = usage.get("findings")
                    if isinstance(fc, int):
                        had_findings_in_degraded = had_findings_in_degraded or fc > 0
                        finding_count = max(finding_count, fc)

            duration_ms = int((time.monotonic() - t0) * 1000)

            # In degraded mode, if there are zero findings, surface a "no
            # findings" skip to make the cron heartbeat visible without
            # spamming run_complete events for empty passive scans.
            if (
                not credentials_available
                and not had_findings_in_degraded
                and finding_count == 0
                and not _had_unavailable_event(result.events)
            ):
                # Even degraded mode emits AgentUnavailable, so this branch
                # is mostly a safety net.
                pass

            _broadcaster().publish(
                notebook_id,
                LintRunComplete(
                    notebook_id=notebook_id,
                    op_id=op_id,
                    finding_count=finding_count,
                    tokens_used=tokens_used,
                    duration_ms=duration_ms,
                    mode=mode,
                ),
            )
            st.last_result = "ran"
            st.last_skip_reason = None
            st.last_finding_count = finding_count
            st.last_seen_mtime = current_mtime
            st.last_run_monotonic = time.monotonic()
            st.last_run_at = time.time()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _had_unavailable_event(events: list[Any]) -> bool:
    for ev in events:
        if isinstance(ev, AgentUnavailable):
            return True
    return False


_MAX_FILES = 10_000


def _max_mtime(notebook_root: Path) -> float:
    """Cheapest possible "anything changed?" probe over wiki + raw.

    Uses ``os.scandir`` recursively (no glob), short-circuits at
    ``_MAX_FILES`` to bound cost on huge notebooks. Returns 0.0 when the
    relevant subtrees don't exist yet.
    """
    max_m = 0.0
    seen = 0
    for sub in ("wiki", "raw"):
        target = notebook_root / sub
        if not target.is_dir():
            continue
        stack = [target]
        while stack and seen < _MAX_FILES:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if seen >= _MAX_FILES:
                            break
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            if entry.is_file(follow_symlinks=False):
                                # For wiki we only care about markdown,
                                # but the cost of stat() is the same so
                                # we just include everything.
                                stat = entry.stat(follow_symlinks=False)
                                if stat.st_mtime > max_m:
                                    max_m = stat.st_mtime
                                seen += 1
                        except OSError:
                            continue
            except OSError:
                continue
    return max_m


__all__ = [
    "LintScheduler",
    "SchedulerStatus",
]
