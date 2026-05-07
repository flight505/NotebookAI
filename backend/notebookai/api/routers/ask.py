"""Ask router: POST /api/notebooks/{id}/ask (sync + SSE) plus chat CRUD."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from notebookai.agent import operations as agent_operations
from notebookai.agent.runtime import AgentRuntime
from notebookai.api.dependencies import (
    AppConfig,
    get_config,
    get_runtime,
    resolve_notebook_root,
)
from notebookai.api.sse import broadcaster, sse_response
from notebookai.chats import Chat, ChatStore, Citation, Message

router = APIRouter(prefix="/notebooks/{notebook_id}", tags=["ask"])


class AskRequest(BaseModel):
    prompt: str = Field(min_length=1)
    archive: bool = False
    stream: bool = False
    chat_id: str | None = None


class AskResponse(BaseModel):
    op_id: str
    answer: str
    citations: list[dict[str, Any]] = []
    commit_sha: str | None = None
    usage: dict[str, Any] = {}
    chat_id: str
    degraded: bool = False


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------


# Match wikilinks `[[path/to/article]]` or `[[path|alias]]`.
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]")


def _citations_from_result(result: agent_operations.OperationResult) -> list[Citation]:
    """Turn an OperationResult into Citation models.

    Pulls Read tool calls (the agent looked at those articles) and any
    `[[wikilink]]`s in the answer body. We keep this best-effort — the
    Phase 6 OperationResult doesn't guarantee a structured `sources`
    field, so we infer from events + text.
    """
    paths: dict[str, Citation] = {}
    # 1) Read tool calls: input.path / input.file_path.
    for ev in result.events or []:
        name = getattr(ev, "_event_name", "")
        if name != "agent.tool_call":
            continue
        tool = getattr(ev, "tool", "")
        if tool != "Read":
            continue
        ev_input = getattr(ev, "input", {}) or {}
        path = ev_input.get("path") or ev_input.get("file_path")
        if not isinstance(path, str):
            continue
        # Only retain paths under wiki/.
        norm = path.lstrip("./")
        if "wiki/" not in norm:
            continue
        # Trim everything before "wiki/" so paths are stable across
        # absolute / relative shapes.
        idx = norm.find("wiki/")
        rel = norm[idx:]
        paths.setdefault(rel, Citation(article_path=rel, quote=""))

    # 2) Wikilinks inside the summary text.
    for m in _WIKILINK_RE.finditer(result.summary or ""):
        target = m.group(1).strip()
        if not target.endswith(".md"):
            target = target + ".md"
        # Wiki-relative path: assume the agent emits links rooted under wiki/.
        rel = target if target.startswith("wiki/") else f"wiki/{target}"
        paths.setdefault(rel, Citation(article_path=rel, quote=""))

    return list(paths.values())


def _ensure_chat(
    store: ChatStore, chat_id: str | None, *, prompt: str, model: str | None
) -> Chat:
    if chat_id:
        existing = store.load_chat(chat_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"chat {chat_id!r} not found")
        return existing
    title = (prompt.strip().splitlines()[0] if prompt.strip() else "New chat")[:60]
    return store.create_chat(title=title or "New chat", model=model)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


async def _ask_event_stream(
    runtime: AgentRuntime,
    notebook_root: Path,
    notebook_id: str,
    *,
    prompt: str,
    archive: bool,
    chat_id: str,
    store: ChatStore,
) -> AsyncIterator[Any]:
    """Run query() and yield its events as they accumulate.

    The driver task runs in the background; when it finishes we persist
    the assistant message (with citations) into the chat markdown.
    """

    final_result: dict[str, agent_operations.OperationResult] = {}

    async def _drive() -> None:
        try:
            result = await agent_operations.smart_query(
                runtime,
                notebook_root,
                prompt=prompt,
                archive=archive,
            )
            final_result["v"] = result
        except Exception as exc:  # noqa: BLE001
            broadcaster.publish(
                notebook_id,
                {
                    "_event_name": "agent.error",
                    "notebook_id": notebook_id,
                    "op_id": "",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "retriable": False,
                },
            )
            return
        for ev in result.events:
            broadcaster.publish(notebook_id, ev)

    task = asyncio.create_task(_drive())
    try:
        async for event in broadcaster.subscribe(notebook_id):
            yield event
            name = getattr(event, "_event_name", "")
            if name in {"agent.done", "agent.error"}:
                break
    finally:
        if task.done():
            result = final_result.get("v")
            if result is not None:
                citations = _citations_from_result(result)
                try:
                    await store.append_message(
                        chat_id,
                        Message(
                            role="assistant",
                            text=result.summary,
                            citations=citations,
                            model=runtime.model,
                            usage=dict(result.usage or {}) or None,
                        ),
                    )
                except Exception:  # noqa: BLE001 — persistence is best effort
                    pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/ask")
async def ask(
    notebook_id: str,
    body: AskRequest,
    config: Annotated[AppConfig, Depends(get_config)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
):
    root = resolve_notebook_root(notebook_id, config)
    store = ChatStore(root)

    chat = _ensure_chat(
        store, body.chat_id, prompt=body.prompt, model=runtime.model
    )

    # Persist the user message right away — even if the agent crashes the
    # transcript will at least record what was asked.
    await store.append_message(
        chat.id, Message(role="user", text=body.prompt)
    )

    if body.stream:
        gen = _ask_event_stream(
            runtime,
            root,
            notebook_id,
            prompt=body.prompt,
            archive=body.archive,
            chat_id=chat.id,
            store=store,
        )
        return sse_response(gen)

    result = await agent_operations.smart_query(
        runtime,
        root,
        prompt=body.prompt,
        archive=body.archive,
    )
    citations = _citations_from_result(result)
    await store.append_message(
        chat.id,
        Message(
            role="assistant",
            text=result.summary,
            citations=citations,
            model=runtime.model,
            usage=dict(result.usage or {}) or None,
        ),
    )

    usage = dict(result.usage or {})
    return AskResponse(
        op_id=result.op_id,
        answer=result.summary,
        citations=[c.model_dump() for c in citations],
        commit_sha=result.commit_sha,
        usage=usage,
        chat_id=chat.id,
        degraded=bool(usage.get("degraded")),
    )


# ---------------------------------------------------------------------------
# Chat CRUD
# ---------------------------------------------------------------------------


class ChatPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get("/chats")
def list_chats(
    notebook_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
):
    root = resolve_notebook_root(notebook_id, config)
    store = ChatStore(root)
    return [s.model_dump(mode="json") for s in store.list_chats()]


@router.get("/chats/{chat_id}")
def get_chat(
    notebook_id: str,
    chat_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
):
    root = resolve_notebook_root(notebook_id, config)
    store = ChatStore(root)
    chat = store.load_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail=f"chat {chat_id!r} not found")
    return chat.model_dump(mode="json")


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(
    notebook_id: str,
    chat_id: str,
    config: Annotated[AppConfig, Depends(get_config)],
):
    root = resolve_notebook_root(notebook_id, config)
    store = ChatStore(root)
    if store.load_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail=f"chat {chat_id!r} not found")
    store.delete_chat(chat_id)


@router.patch("/chats/{chat_id}")
def patch_chat(
    notebook_id: str,
    chat_id: str,
    body: ChatPatch,
    config: Annotated[AppConfig, Depends(get_config)],
):
    root = resolve_notebook_root(notebook_id, config)
    store = ChatStore(root)
    if store.load_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail=f"chat {chat_id!r} not found")
    store.rename_chat(chat_id, body.title)
    chat = store.load_chat(chat_id)
    assert chat is not None
    return chat.model_dump(mode="json")


__all__ = ["router"]
