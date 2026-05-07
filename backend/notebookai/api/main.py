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


def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
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
