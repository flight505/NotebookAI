"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from notebookai.api.dependencies import (
    AppConfig,
    dispose_caches,
    get_config,
    get_runtime,
    get_scheduler,
)
from notebookai.api.routers import (
    articles,
    ask,
    events,
    history,
    ingest,
    internal,
    library,
    lint,
    log,
    notebooks,
)
from notebookai.api.sse import broadcaster

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:1420",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:1420",
]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Own the runtime / scheduler / broadcaster for the lifetime of the app.

    Singletons are mirrored on ``app.state`` so the ``/api/internal/state``
    endpoint and tests can introspect them without relying on the module-level
    ``lru_cache``. On shutdown we stop the scheduler, drain SSE subscribers,
    and dispose the caches so a follow-up boot in the same process (e.g.
    pytest's repeated TestClient lifespans) never reuses a stale instance.
    """
    runtime = get_runtime()
    scheduler = get_scheduler()
    app.state.runtime = runtime
    app.state.scheduler = scheduler
    app.state.broadcaster = broadcaster
    scheduler.start()
    try:
        yield
    finally:
        try:
            scheduler.stop()
        finally:
            try:
                await broadcaster.close_all_subscribers()
            finally:
                dispose_caches()


def create_app(*, config: AppConfig | None = None) -> FastAPI:
    """Build a FastAPI app instance."""
    app = FastAPI(
        title="NotebookAI",
        version="0.1.0",
        lifespan=_lifespan,
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

    # Mount the routers under /api.
    app.include_router(notebooks.router, prefix="/api")
    app.include_router(library.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(lint.router, prefix="/api")
    app.include_router(articles.router, prefix="/api")
    app.include_router(log.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(internal.router, prefix="/api")

    return app


__all__ = ["create_app"]
