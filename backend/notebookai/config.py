"""Centralized configuration for NotebookAI.

Reads every env var documented in ``backend/.env.example`` via
pydantic-settings v2. Use :func:`get_config` everywhere instead of
hardcoding ports, paths, or model names.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_library_root() -> Path:
    return Path.home() / "NotebookAI" / "notebooks"


class NotebookAIConfig(BaseSettings):
    """All env-driven configuration for the NotebookAI backend."""

    # Class-level constants — single source of truth for defaults.
    API_PORT: int = 8765
    API_HOST: str = "127.0.0.1"
    LIBRARY_ROOT_DEFAULT: Path = Path.home() / "NotebookAI" / "notebooks"

    model_config = SettingsConfigDict(
        env_prefix="",  # we declare the full env name on each field
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Anthropic auth — optional. OAuth via `claude setup-token` is preferred
    # for personal use and is detected separately by AgentRuntime.
    anthropic_api_key: str | None = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY"
    )

    # Library + API.
    library_root: Path = Field(
        default_factory=_default_library_root,
        validation_alias="NOTEBOOKAI_LIBRARY_ROOT",
    )
    api_host: str = Field(default="127.0.0.1", validation_alias="NOTEBOOKAI_API_HOST")
    api_port: int = Field(default=8765, validation_alias="NOTEBOOKAI_API_PORT")

    # Models.
    agent_model: str = Field(
        default="claude-sonnet-4-6", validation_alias="NOTEBOOKAI_AGENT_MODEL"
    )
    lint_model: str = Field(
        default="claude-haiku-4-5-20251001",
        validation_alias="NOTEBOOKAI_LINT_MODEL",
    )

    # Lint budgets.
    lint_budget_input: int = Field(
        default=50_000, validation_alias="NOTEBOOKAI_LINT_BUDGET_INPUT"
    )
    lint_budget_output: int = Field(
        default=10_000, validation_alias="NOTEBOOKAI_LINT_BUDGET_OUTPUT"
    )

    # Embeddings.
    emb_model: str = Field(
        default="BAAI/bge-small-en-v1.5", validation_alias="NOTEBOOKAI_EMB_MODEL"
    )

    # Logging.
    log_level: str = Field(default="INFO", validation_alias="NOTEBOOKAI_LOG_LEVEL")

    # Convenience helpers.
    def trash_dir(self) -> Path:
        return self.library_root.parent / ".trash"

    def default_config_file(self) -> Path:
        return self.library_root.parent / "config.json"


@lru_cache(maxsize=1)
def get_config() -> NotebookAIConfig:
    """Return the cached :class:`NotebookAIConfig` singleton."""
    return NotebookAIConfig()


def reset_config_cache() -> None:
    """Test helper: clear the cached config."""
    get_config.cache_clear()


__all__ = [
    "NotebookAIConfig",
    "get_config",
    "reset_config_cache",
]
