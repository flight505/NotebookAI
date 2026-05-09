"""Internal introspection endpoints.

Surfaces a snapshot of the long-lived process state — the registered scheduler
intervals, current SSE subscriber counts, and runtime model selections — to
ease curate-mode debugging and to give Tauri a deterministic hook for
"is the backend healthy and ready?" beyond ``/healthz``.

The route is intentionally local-only (FastAPI binds 127.0.0.1 by default and
CORS only whitelists localhost origins). No auth surface is added.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/state")
def get_state(request: Request) -> dict[str, Any]:
    """Return a JSON snapshot of runtime / scheduler / broadcaster."""
    state = request.app.state
    runtime = getattr(state, "runtime", None)
    scheduler = getattr(state, "scheduler", None)
    broadcaster = getattr(state, "broadcaster", None)

    runtime_payload: dict[str, Any] = {}
    if runtime is not None:
        runtime_payload = {
            "model": getattr(runtime, "model", None),
            "lint_model": getattr(runtime, "lint_model", None),
            "credentials_available": runtime.credentials_available()
            if hasattr(runtime, "credentials_available")
            else None,
        }

    scheduler_payload: dict[str, Any] = {}
    if scheduler is not None:
        # ``_states`` is the per-notebook bookkeeping map. Keys are notebook
        # ids; values include the live ``asyncio.Task`` which we can't
        # serialise. Project just what the dashboard cares about.
        states_map = getattr(scheduler, "_states", {}) or {}
        scheduler_payload = {
            "default_interval_minutes": getattr(
                scheduler, "default_interval_minutes", None
            ),
            "notebooks": {
                nb_id: {
                    "enabled": getattr(st, "enabled", None),
                    "interval_minutes": getattr(st, "interval_minutes", None),
                    "last_result": getattr(st, "last_result", None),
                    "last_run_at": getattr(st, "last_run_at", None),
                    "running": st.lock.locked() if getattr(st, "lock", None) else False,
                }
                for nb_id, st in states_map.items()
            },
        }

    broadcaster_payload: dict[str, Any] = {}
    if broadcaster is not None:
        channels = getattr(broadcaster, "_channels", {}) or {}
        broadcaster_payload = {
            "subscriber_counts": {
                nb_id: len(qs) for nb_id, qs in channels.items()
            }
        }

    return {
        "runtime": runtime_payload,
        "scheduler": scheduler_payload,
        "broadcaster": broadcaster_payload,
    }


__all__ = ["router"]
