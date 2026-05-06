"""Git integration: per-op commits, history reads, oplog fallback.

Re-exports the public surface of :mod:`notebookai.git.notebook_repo`.
"""

from __future__ import annotations

from notebookai.git.notebook_repo import (
    Commit,
    NotebookRepo,
    OpLogEntry,
)

__all__ = ["Commit", "NotebookRepo", "OpLogEntry"]
