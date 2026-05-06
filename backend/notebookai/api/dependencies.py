"""Shared dependencies for the API: config + DI factories."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from notebookai.agent.runtime import AgentRuntime
from notebookai.scaffold import NotebookMeta


def _default_library_root() -> Path:
    return Path.home() / "NotebookAI" / "notebooks"


class AppConfig(BaseSettings):
    """API configuration loaded from env (prefix: ``NOTEBOOKAI_``)."""

    model_config = SettingsConfigDict(
        env_prefix="NOTEBOOKAI_",
        env_file=None,
        extra="ignore",
    )

    library_root: Path = Field(default_factory=_default_library_root)
    agent_model: str = "claude-sonnet-4-6"
    agent_lint_model: str = "claude-haiku-4-5-20251001"
    config_file: Path | None = None  # for ``extra_notebook_roots`` etc.

    def trash_dir(self) -> Path:
        return self.library_root.parent / ".trash"

    def resolved_config_file(self) -> Path:
        return self.config_file or (self.library_root.parent / "config.json")

    def read_config(self) -> dict:
        path = self.resolved_config_file()
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def write_config(self, data: dict) -> None:
        path = self.resolved_config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def _cached_config() -> AppConfig:
    return AppConfig()


def get_config() -> AppConfig:
    """FastAPI dependency: returns the cached AppConfig."""
    return _cached_config()


def reset_config_cache() -> None:
    """Test helper: clear the cached AppConfig + Runtime."""
    _cached_config.cache_clear()
    _cached_runtime.cache_clear()


@lru_cache(maxsize=1)
def _cached_runtime() -> AgentRuntime:
    cfg = _cached_config()
    return AgentRuntime(model=cfg.agent_model, lint_model=cfg.agent_lint_model)


def get_runtime() -> AgentRuntime:
    """FastAPI dependency: returns the cached AgentRuntime."""
    return _cached_runtime()


def resolve_notebook_root(notebook_id: str, config: AppConfig) -> Path:
    """Return the absolute path to a notebook root, or 404."""
    root = config.library_root / notebook_id
    if not root.is_dir() or not (root / ".notebookai" / "notebook.json").is_file():
        raise HTTPException(status_code=404, detail=f"notebook {notebook_id!r} not found")
    return root.resolve()


def get_notebook_meta(notebook_id: str, config: AppConfig) -> NotebookMeta:
    """Read and validate ``notebook.json`` for the given id."""
    root = resolve_notebook_root(notebook_id, config)
    meta_path = root / ".notebookai" / "notebook.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"corrupt notebook.json: {exc}") from exc
    return NotebookMeta.model_validate(data)


__all__ = [
    "AppConfig",
    "get_config",
    "get_runtime",
    "reset_config_cache",
    "resolve_notebook_root",
    "get_notebook_meta",
]
