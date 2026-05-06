"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from notebookai.api.dependencies import AppConfig, get_config
from notebookai.api.routers import (
    articles,
    ask,
    events,
    history,
    ingest,
    library,
    lint,
    log,
    notebooks,
)

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:1420",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:1420",
]


def create_app(*, config: AppConfig | None = None) -> FastAPI:
    """Build a FastAPI app instance."""
    app = FastAPI(
        title="NotebookAI",
        version="0.1.0",
    )

    if config is not None:
        app.dependency_overrides[get_config] = lambda: config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": "NotebookAI", "version": app.version, "status": "ok"}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Mount the nine routers under /api.
    app.include_router(notebooks.router, prefix="/api")
    app.include_router(library.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(lint.router, prefix="/api")
    app.include_router(articles.router, prefix="/api")
    app.include_router(log.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(events.router, prefix="/api")

    return app


__all__ = ["create_app"]
