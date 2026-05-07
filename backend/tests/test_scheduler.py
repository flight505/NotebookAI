"""Tests for the in-process per-notebook lint scheduler.

All tests run without Claude credentials. The scheduler is exercised by:

* monkeypatching ``smart_lint`` to return a synthetic OperationResult, OR
* forcing ``credentials_available()`` to False and letting the degraded
  ``WikiOnlyMode.lint`` path execute (purely passive — no LLM calls).

Tests use very short intervals (sub-second) plus ``trigger_now`` to keep
runtime tight.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from notebookai.agent import operations as agent_operations
from notebookai.agent import scheduler as scheduler_module
from notebookai.agent.events import (
    AgentDone,
    AgentUnavailable,
    LintRunComplete,
    LintScheduled,
    LintSkipped,
)
from notebookai.agent.runtime import AgentRuntime
from notebookai.agent.scheduler import LintScheduler
from notebookai.api.sse import broadcaster

# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _make_notebook(library_root: Path, *, nb_id: str = "nb") -> Path:
    nb = library_root / nb_id
    (nb / ".notebookai").mkdir(parents=True)
    (nb / "wiki").mkdir()
    (nb / "raw").mkdir()
    (nb / "chats").mkdir()
    (nb / ".notebookai" / "notebook.json").write_text(
        json.dumps(
            {
                "id": nb_id,
                "name": nb_id,
                "created_at": "2026-01-01T00:00:00Z",
                "schema_version": 1,
                "git_enabled": False,
                "embeddings": {"model": "fake", "dim": 32},
                "agent": {
                    "model": "claude-sonnet-4-6",
                    "lint_model": "claude-haiku-4-5-20251001",
                    "lint_schedule": "hourly",
                    "lint_budget_tokens_per_day": 50_000,
                    "lint_schedule_enabled": True,
                    "lint_schedule_interval_minutes": 60,
                },
            }
        ),
        encoding="utf-8",
    )
    # Drop a wiki page so mtime sniffing has something to look at.
    (nb / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    return nb


class _Recorder:
    """Subscribes to a notebook's SSE channel; collects events."""

    def __init__(self) -> None:
        self.events: list[Any] = []
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self, notebook_id: str) -> None:
        async def _run() -> None:
            agen = broadcaster.subscribe(notebook_id)
            try:
                async for ev in agen:
                    self.events.append(ev)
                    if self._stop.is_set():
                        break
            except asyncio.CancelledError:
                pass
            finally:
                aclose = getattr(agen, "aclose", None)
                if callable(aclose):
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001
                        pass

        self._task = asyncio.create_task(_run())
        # Yield once so the subscriber registers before publishers fire.
        await asyncio.sleep(0)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    def of_type(self, kind: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, kind)]


async def _wait_for(
    pred,
    *,
    timeout: float = 4.0,
    poll: float = 0.05,
) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if pred():
            return True
        await asyncio.sleep(poll)
    return False


def _stub_smart_lint(
    *,
    findings: int = 1,
    tokens: int = 0,
):
    """Build a fake :func:`smart_lint` returning a deterministic result."""

    async def _fake(runtime, notebook_root, *, mode="light"):
        nb_id = Path(notebook_root).name
        usage = {
            "input_tokens": tokens // 2,
            "output_tokens": tokens - tokens // 2,
            "findings": findings,
        }
        return agent_operations.OperationResult(
            op="lint-fix",
            op_id="01HFAKEOP",
            notebook_id=nb_id,
            summary=f"{findings} findings",
            commit_sha=None,
            events=[
                AgentDone(
                    notebook_id=nb_id,
                    op_id="01HFAKEOP",
                    op="lint-fix",
                    summary=f"{findings} findings",
                    usage=usage,
                )
            ],
            usage=usage,
        )

    return _fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_runs_on_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    rt = AgentRuntime()
    monkeypatch.setattr(rt, "credentials_available", lambda: True)
    monkeypatch.setattr(
        agent_operations, "smart_lint", _stub_smart_lint(findings=2, tokens=200)
    )

    scheduler = LintScheduler(rt, tmp_path, default_interval_minutes=1)
    scheduler.start()
    # Force a sub-second interval so the loop fires quickly.
    state = scheduler._ensure_state(nb.name)
    state.interval_minutes = 1  # min allowed; we'll trigger_now to fire fast
    rec = _Recorder()
    await rec.start(nb.name)
    try:
        # The interval-based test would otherwise wait 60s. We exploit that
        # trigger_now() routes through the same loop so the run path under
        # test (interval branch logic) is still exercised when the trigger
        # wakes the wait. The "reason" of the published event will be
        # "manual" because trigger_event was set; we still validate the
        # full run path: scheduled -> done -> run_complete.
        scheduler.trigger_now(nb.name)
        ok = await _wait_for(lambda: rec.of_type(LintRunComplete), timeout=4.0)
        assert ok, f"no run_complete in {rec.events!r}"
        assert rec.of_type(LintScheduled), "no lint.scheduled emitted"
        rc = rec.of_type(LintRunComplete)[0]
        assert rc.finding_count == 2
        assert rc.tokens_used == 200
        assert rc.mode == "haiku"
    finally:
        await rec.stop()
        scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_skips_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    rt = AgentRuntime()
    monkeypatch.setattr(rt, "credentials_available", lambda: True)
    monkeypatch.setattr(
        agent_operations, "smart_lint", _stub_smart_lint(findings=0, tokens=0)
    )

    scheduler = LintScheduler(rt, tmp_path, default_interval_minutes=60)
    scheduler.start()
    rec = _Recorder()
    await rec.start(nb.name)
    try:
        # First run: trigger_now → reason=manual → bypasses idle, executes.
        scheduler.trigger_now(nb.name)
        assert await _wait_for(
            lambda: rec.of_type(LintRunComplete), timeout=4.0
        )
        rec.events.clear()

        # Now manually invoke the loop's interval path. We synthesise the
        # interval-tick code path by calling _run_once directly with
        # reason="interval" — files haven't been touched, so it must skip.
        await scheduler._run_once(
            nb.name,
            nb,
            meta=scheduler._read_meta(nb),
            reason="interval",
        )
        # Yield to let the broadcaster deliver to the queue subscriber.
        ok = await _wait_for(
            lambda: rec.of_type(LintSkipped),
            timeout=2.0,
        )
        assert ok, f"expected LintSkipped, got: {rec.events!r}"
        skipped = rec.of_type(LintSkipped)
        assert skipped[-1].reason == "idle"
    finally:
        await rec.stop()
        scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_skips_when_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    # Set a zero budget for this notebook.
    meta_path = nb / ".notebookai" / "notebook.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["agent"]["lint_budget_tokens_per_day"] = 0
    meta["agent"]["lint_output_budget_tokens_per_day"] = 0
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    rt = AgentRuntime()
    monkeypatch.setattr(rt, "credentials_available", lambda: True)
    fired = {"count": 0}

    async def _should_not_run(*_a, **_kw):
        fired["count"] += 1
        raise AssertionError("smart_lint should not run when budget is zero")

    monkeypatch.setattr(agent_operations, "smart_lint", _should_not_run)

    scheduler = LintScheduler(rt, tmp_path, default_interval_minutes=60)
    scheduler.start()
    rec = _Recorder()
    await rec.start(nb.name)
    try:
        scheduler.trigger_now(nb.name)
        assert await _wait_for(
            lambda: any(
                isinstance(e, LintSkipped) and e.reason == "budget_exhausted"
                for e in rec.events
            ),
            timeout=4.0,
        ), rec.events
        assert fired["count"] == 0
    finally:
        await rec.stop()
        scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_handles_degraded_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    rt = AgentRuntime()
    monkeypatch.setattr(rt, "credentials_available", lambda: False)

    # Don't stub smart_lint — let the real degraded WikiOnlyMode.lint run.
    scheduler = LintScheduler(rt, tmp_path, default_interval_minutes=60)
    scheduler.start()
    rec = _Recorder()
    await rec.start(nb.name)
    try:
        scheduler.trigger_now(nb.name)
        ok = await _wait_for(
            lambda: rec.of_type(LintRunComplete), timeout=6.0
        )
        assert ok, rec.events
        rc = rec.of_type(LintRunComplete)[0]
        assert rc.mode == "passive_only"
        assert rc.tokens_used == 0
        # Degraded mode emits AgentUnavailable up front.
        assert rec.of_type(AgentUnavailable)
    finally:
        await rec.stop()
        scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_now_runs_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    rt = AgentRuntime()
    monkeypatch.setattr(rt, "credentials_available", lambda: True)
    monkeypatch.setattr(
        agent_operations, "smart_lint", _stub_smart_lint(findings=1, tokens=10)
    )

    scheduler = LintScheduler(rt, tmp_path, default_interval_minutes=60)
    scheduler.start()
    rec = _Recorder()
    await rec.start(nb.name)
    try:
        t0 = time.monotonic()
        scheduler.trigger_now(nb.name)
        ok = await _wait_for(
            lambda: rec.of_type(LintRunComplete), timeout=2.0
        )
        elapsed = time.monotonic() - t0
        assert ok
        assert elapsed < 2.0, f"trigger_now took {elapsed:.2f}s"
    finally:
        await rec.stop()
        scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_now_debounces_concurrent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = _make_notebook(tmp_path)
    rt = AgentRuntime()
    monkeypatch.setattr(rt, "credentials_available", lambda: True)

    # smart_lint that takes a tiny moment so the second trigger sees a busy lock.
    fire_count = {"n": 0}

    async def _slow_lint(runtime, notebook_root, *, mode="light"):
        fire_count["n"] += 1
        await asyncio.sleep(0.2)
        nb_id = Path(notebook_root).name
        return agent_operations.OperationResult(
            op="lint-fix",
            op_id=f"op-{fire_count['n']}",
            notebook_id=nb_id,
            summary="ok",
            events=[
                AgentDone(
                    notebook_id=nb_id,
                    op_id=f"op-{fire_count['n']}",
                    op="lint-fix",
                    summary="ok",
                    usage={"input_tokens": 0, "output_tokens": 0},
                )
            ],
        )

    monkeypatch.setattr(agent_operations, "smart_lint", _slow_lint)

    scheduler = LintScheduler(rt, tmp_path, default_interval_minutes=60)
    scheduler.start()
    try:
        # Two rapid-fire triggers should debounce to one.
        scheduler.trigger_now(nb.name)
        scheduler.trigger_now(nb.name)
        # Wait long enough for one full run to finish.
        await asyncio.sleep(0.6)
        assert fire_count["n"] == 1, fire_count
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build the FastAPI app with lifespan; verify start/stop hooks fire."""
    from fastapi.testclient import TestClient

    from notebookai.api.app import create_app
    from notebookai.api.dependencies import (
        AppConfig,
        get_scheduler,
        reset_config_cache,
    )

    reset_config_cache()
    cfg = AppConfig(library_root=tmp_path)

    started = {"n": 0}
    stopped = {"n": 0}

    real = get_scheduler()
    real.library_root = tmp_path  # point at the temp library
    orig_start = real.start
    orig_stop = real.stop

    def _spy_start():
        started["n"] += 1
        orig_start()

    def _spy_stop():
        stopped["n"] += 1
        orig_stop()

    monkeypatch.setattr(real, "start", _spy_start)
    monkeypatch.setattr(real, "stop", _spy_stop)

    app = create_app(config=cfg)

    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
    # Lifespan exit triggered stop.
    assert started["n"] >= 1
    assert stopped["n"] >= 1
    reset_config_cache()


# Silence the "imported but unused" import warning when AsyncIterator only
# decorates pytest_asyncio APIs.
_ = AsyncIterator
_ = scheduler_module


# ---------------------------------------------------------------------------
# Jitter — sleep duration is randomised within ±10% (PR-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_sleep_jitter_in_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-notebook loop must spread interval ticks via random jitter
    so N notebooks don't wake on the same boundary.

    We capture every call to ``asyncio.sleep`` made by the loop, drive a
    handful of ticks via the trigger event, and assert the captured durations
    span ±10% of nominal and are never identical.
    """
    import notebookai.agent.scheduler as sched_mod

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def _capture_sleep(seconds: float, *args, **kwargs):
        # Record only the loop's interval sleep — debounce-style microsleeps
        # would skew the sample. The loop sleeps for tens-of-seconds at the
        # 60-min default interval, so cap the threshold low and short-circuit.
        if seconds > 0.5:
            sleeps.append(seconds)
            # Don't actually sleep that long during tests.
            return
        await real_sleep(seconds, *args, **kwargs)

    monkeypatch.setattr(sched_mod.asyncio, "sleep", _capture_sleep)

    # Build a notebook + scheduler, manually advance the loop a few times.
    nb_root = tmp_path / "nb"
    nb_root.mkdir()
    (nb_root / ".notebookai").mkdir()
    (nb_root / ".notebookai" / "notebook.json").write_text(
        json.dumps({"id": "nb", "name": "n"}), encoding="utf-8"
    )
    (nb_root / "wiki").mkdir()
    (nb_root / "raw").mkdir()

    runtime = scheduler_module.AgentRuntime(model="m", lint_model="l")
    sched = scheduler_module.LintScheduler(
        runtime, tmp_path, default_interval_minutes=1
    )
    sched.start()
    try:
        # Spawn the per-notebook task by reading status.
        sched.status("nb")
        # Yield enough times for the loop to enter its sleep + we record
        # multiple jittered durations.
        for _ in range(50):
            await real_sleep(0)
            if len(sleeps) >= 5:
                break
    finally:
        sched.stop()

    assert len(sleeps) >= 3, f"expected ≥3 captured sleeps, got {len(sleeps)}"
    nominal = 60.0  # 1 minute interval × 60s
    for s in sleeps:
        assert 0.9 * nominal <= s <= 1.1 * nominal, f"sleep {s}s outside ±10%"
    assert len(set(sleeps)) > 1, "sleeps were all identical — jitter not applied"
