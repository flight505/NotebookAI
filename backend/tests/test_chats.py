"""Tests for the markdown-canonical chat store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from notebookai.chats import Chat, ChatStore, Citation, Message


@pytest.fixture
def store(tmp_path: Path) -> ChatStore:
    nb_root = tmp_path / "notebook"
    nb_root.mkdir()
    return ChatStore(nb_root)


def test_create_and_load_roundtrip(store: ChatStore):
    chat = store.create_chat(title="Attention mechanisms", model="claude-sonnet-4-6")
    loaded = store.load_chat(chat.id)
    assert loaded is not None
    assert loaded.id == chat.id
    assert loaded.title == "Attention mechanisms"
    assert loaded.model == "claude-sonnet-4-6"
    assert loaded.messages == []


def test_append_message_persisted(store: ChatStore):
    chat = store.create_chat(title="Q&A")
    store.append_message_sync(
        chat.id, Message(role="user", text="What is attention?")
    )
    store.append_message_sync(
        chat.id,
        Message(role="assistant", text="It's a mechanism.", model="claude-sonnet-4-6"),
    )
    store.append_message_sync(
        chat.id, Message(role="user", text="Tell me more.")
    )
    loaded = store.load_chat(chat.id)
    assert loaded is not None
    assert len(loaded.messages) == 3
    assert loaded.messages[0].role == "user"
    assert loaded.messages[0].text == "What is attention?"
    assert loaded.messages[1].role == "assistant"
    assert loaded.messages[1].model == "claude-sonnet-4-6"


def test_list_chats_summary(store: ChatStore):
    titles = [f"Chat {i}" for i in range(5)]
    for t in titles:
        store.create_chat(title=t)
    summaries = store.list_chats()
    assert len(summaries) == 5
    assert {s.title for s in summaries} == set(titles)
    for s in summaries:
        assert s.message_count == 0


def test_rename_chat(store: ChatStore):
    chat = store.create_chat(title="Old title")
    store.rename_chat(chat.id, "New title")
    loaded = store.load_chat(chat.id)
    assert loaded is not None
    assert loaded.title == "New title"


def test_delete_chat_moves_to_trash(store: ChatStore):
    chat = store.create_chat(title="Trash me")
    store.delete_chat(chat.id)
    assert store.load_chat(chat.id) is None
    trashed = list((store.chats_dir / ".trash").glob("*.md"))
    assert len(trashed) == 1


def test_external_edit_preserves_id(store: ChatStore):
    """If a human edits the markdown body externally, id + title still parse."""
    chat = store.create_chat(title="External edit")
    store.append_message_sync(
        chat.id, Message(role="user", text="hello")
    )
    # Locate the file and rewrite the body — but keep frontmatter intact.
    path = next(store.chats_dir.glob("*.md"))
    text = path.read_text(encoding="utf-8")
    # Append a hand-written section.
    text += (
        "\n## assistant · 2026-05-06T12:00:00Z\n\n"
        "Hand-written reply.\n"
    )
    path.write_text(text, encoding="utf-8")

    loaded = store.load_chat(chat.id)
    assert loaded is not None
    assert loaded.id == chat.id
    assert loaded.title == "External edit"
    # The hand-written assistant message should round-trip.
    assert any(
        m.role == "assistant" and "Hand-written" in m.text
        for m in loaded.messages
    )


def test_concurrent_append_safety(store: ChatStore):
    """Parallel async appends to the same chat produce the right final count.

    Strategy: ChatStore keeps a per-path ``asyncio.Lock`` so writes to
    the same chat serialise. We schedule N appends concurrently and
    verify all of them land.
    """
    chat = store.create_chat(title="Concurrent")

    async def runner() -> None:
        await asyncio.gather(
            *(
                store.append_message(
                    chat.id, Message(role="user", text=f"msg {i}")
                )
                for i in range(20)
            )
        )

    asyncio.run(runner())
    loaded = store.load_chat(chat.id)
    assert loaded is not None
    assert len(loaded.messages) == 20


def test_message_with_citations_roundtrip(store: ChatStore):
    chat = store.create_chat(title="Cited")
    msg = Message(
        role="assistant",
        text="The answer relies on attention.",
        citations=[
            Citation(
                article_path="wiki/ml/transformers.md",
                quote="Multi-head attention allows the model",
                score=0.91,
            ),
            Citation(
                article_path="wiki/ml/attention.md",
                quote="Scaled dot-product attention is the foundation.",
                score=None,
            ),
        ],
        model="claude-sonnet-4-6",
        usage={"input_tokens": 850, "output_tokens": 420},
    )
    store.append_message_sync(chat.id, msg)
    loaded = store.load_chat(chat.id)
    assert loaded is not None
    assert len(loaded.messages) == 1
    cs = loaded.messages[0].citations
    assert len(cs) == 2
    assert cs[0].article_path == "wiki/ml/transformers.md"
    assert "Multi-head attention" in cs[0].quote
    assert cs[0].score == pytest.approx(0.91, abs=1e-3)
    assert cs[1].article_path == "wiki/ml/attention.md"
    assert cs[1].score is None
