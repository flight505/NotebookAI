"""Notebooks router: create / read / patch / delete."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from notebookai.agent.passive_watcher import supervisor as passive_watcher_supervisor
from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    get_notebook_meta,
    resolve_notebook_root,
)
from notebookai.index.store import IndexStore
from notebookai.scaffold import NotebookMeta, create_notebook

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


class CreateNotebookRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    git_enabled: bool = True
    description: str | None = Field(default=None, max_length=512)


class PatchNotebookRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=NotebookMeta)
def create(
    body: CreateNotebookRequest,
    config: Annotated[AppConfig, Depends(get_config)],
) -> NotebookMeta:
    config.library_root.mkdir(parents=True, exist_ok=True)
    try:
        handle = create_notebook(
            config.library_root,
            body.name,
            git_enabled=body.git_enabled,
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"notebook already exists: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.description:
        meta = handle.meta.model_copy(update={"description": body.description})
        (handle.root / ".notebookai" / "notebook.json").write_text(
            meta.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        _ensure_passive_watcher(meta.id, handle.root)
        return meta
    _ensure_passive_watcher(handle.meta.id, handle.root)
    return handle.meta


@router.get("/{notebook_id}", response_model=NotebookMeta)
def read(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> NotebookMeta:
    meta = get_notebook_meta(notebook_id, config)
    _ensure_passive_watcher(notebook_id, resolve_notebook_root(notebook_id, config))
    return meta


@router.patch("/{notebook_id}", response_model=NotebookMeta)
def patch(
    notebook_id: str,
    body: PatchNotebookRequest,
    config: Annotated[AppConfig, Depends(get_config)],
) -> NotebookMeta:
    meta = get_notebook_meta(notebook_id, config)
    update: dict = {}
    if body.name is not None:
        update["name"] = body.name
    if body.description is not None:
        update["description"] = body.description
    if not update:
        return meta
    new_meta = meta.model_copy(update=update)
    root = resolve_notebook_root(notebook_id, config)
    (root / ".notebookai" / "notebook.json").write_text(
        new_meta.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return new_meta


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> Response:
    root = resolve_notebook_root(notebook_id, config)
    trash_root = config.trash_dir()
    trash_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = trash_root / f"{notebook_id}-{ts}"
    shutil.move(str(root), str(target))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]


# Helper: load meta lazily without import cycles
def _read_meta(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _ensure_passive_watcher(notebook_id: str, root) -> None:
    """Idempotent registration of the passive watcher for a notebook.

    The supervisor is a process-singleton; this just primes its store so
    on_event callers downstream can persist findings without rebooting.
    """
    try:
        store = IndexStore(root)
        store.bootstrap()
    except Exception:  # noqa: BLE001
        return
    passive_watcher_supervisor.get(notebook_id, store=store)
