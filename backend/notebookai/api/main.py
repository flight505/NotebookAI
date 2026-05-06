"""Console entrypoint: run the API server with uvicorn."""

from __future__ import annotations

import logging

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


def run() -> None:
    """Console-script entry point: ``notebookai-api``."""
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
