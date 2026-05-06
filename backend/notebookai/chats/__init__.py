"""Chats package — markdown-canonical chat persistence.

Per CONTRACTS § Decisions row 2: chat markdown files on disk are the
canonical source of truth. Anything in SQLite is a derived index.

Chats live at ``<notebook_root>/chats/<YYYY-MM-DD>-<slug>.md``.
"""

from notebookai.chats.store import (
    Chat,
    ChatStore,
    ChatSummary,
    Citation,
    Message,
)

__all__ = [
    "Chat",
    "ChatStore",
    "ChatSummary",
    "Citation",
    "Message",
]
