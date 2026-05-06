"""Console entrypoint: run the API server with uvicorn."""

from __future__ import annotations

import logging

import structlog


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def run() -> None:
    """Console-script entry point: ``notebookai-api``."""
    _configure_logging()
    import uvicorn

    uvicorn.run(
        "notebookai.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
