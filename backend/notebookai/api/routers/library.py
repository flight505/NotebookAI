"""Library router: list discovered notebooks + register/deregister externals."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from notebookai.api.dependencies import AppConfig, get_config
from notebookai.library import (
    LibraryScanner,
    NotebookEntry,
    load_library_config,
)

router = APIRouter(prefix="/library", tags=["library"])


class RegisterRequest(BaseModel):
    path: str = Field(min_length=1)


def _scanner_for(config: AppConfig) -> LibraryScanner:
    config_path = config.resolved_config_file()
    cfg = load_library_config(config_path)
    extras = [Path(p) for p in (cfg.get("extra_notebook_roots", []) or [])]
    return LibraryScanner(
        library_root=config.library_root,
        extra_roots=extras,
        config_path=config_path,
    )


@router.get("", response_model=list[NotebookEntry])
def list_library(
    config: Annotated[AppConfig, Depends(get_config)],
) -> list[NotebookEntry]:
    return _scanner_for(config).scan()


@router.post("/register", response_model=NotebookEntry)
def register_external(
    body: RegisterRequest,
    config: Annotated[AppConfig, Depends(get_config)],
) -> NotebookEntry:
    scanner = _scanner_for(config)
    raw = Path(body.path).expanduser()
    if not raw.is_absolute():
        raise HTTPException(status_code=400, detail="path must be absolute")
    try:
        return scanner.register_external(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/external/{encoded_path}", status_code=status.HTTP_204_NO_CONTENT
)
def deregister_external(
    encoded_path: str,
    config: Annotated[AppConfig, Depends(get_config)],
) -> None:
    try:
        decoded = base64.urlsafe_b64decode(encoded_path.encode("ascii")).decode(
            "utf-8"
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid encoded_path: {exc}"
        ) from exc
    scanner = _scanner_for(config)
    scanner.deregister_external(Path(decoded))


__all__ = ["router"]
