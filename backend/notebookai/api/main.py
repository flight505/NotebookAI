"""Console entrypoint: run the API server with uvicorn.

Also the frozen-binary entry point — when bundled by PyInstaller (`sys.frozen`
is set on the bootloader), uvicorn must be invoked without ``reload=True``
because there's no source tree to watch and the multiprocessing worker model
breaks under the frozen runtime.
"""

from __future__ import annotations

import logging
import multiprocessing
import sys

import structlog

from notebookai.config import get_config

# Pin "spawn" as the multiprocessing start method at import time. macOS already
# defaults to spawn since 3.8, but Linux defaults to "fork", and forking after
# we've initialised CUDA/Tokenizers/asyncio workers is a known source of dead-
# locks (e.g. sentence-transformers + uvicorn). ``force=False`` keeps any
# explicit caller setting; we only set it if no method has been chosen yet.
try:  # pragma: no cover - exercised by import side effect
    multiprocessing.set_start_method("spawn", force=False)
except (RuntimeError, ValueError):
    # RuntimeError if already set; ValueError if the platform doesn't support
    # spawn (none we target). Either way there's nothing to fix.
    pass


def _configure_logging(level: str = "INFO") -> None:
    """Wire stdlib + structlog. TTY → coloured ConsoleRenderer; pipes → JSON.

    Choosing the renderer based on ``stdout.isatty()`` lets a developer running
    ``notebookai-api`` in a terminal see human-readable logs while a packaged
    sidecar (whose stdout is captured by the Tauri shell) keeps emitting JSON
    that downstream tooling can parse.
    """
    logging.basicConfig(level=level)
    is_tty = sys.stdout.isatty()
    renderer = (
        structlog.dev.ConsoleRenderer(colors=True)
        if is_tty
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ]
    )


def _is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) bundled binary."""
    return bool(getattr(sys, "frozen", False))


def run() -> None:
    """Console-script entry point: ``notebookai-api``.

    Also invoked by the PyInstaller-built sidecar binary. In frozen mode we
    pin ``reload=False`` and call :func:`multiprocessing.freeze_support` so
    that any internal worker spawn paths don't re-execute the bootloader.
    """
    if _is_frozen():
        multiprocessing.freeze_support()

    config = get_config()
    _configure_logging(config.log_level)
    import uvicorn

    uvicorn.run(
        "notebookai.api.app:create_app",
        factory=True,
        host=config.api_host,
        port=config.api_port,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
