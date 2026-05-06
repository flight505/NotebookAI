"""Library scanner: discover notebooks across configured roots.

A folder is a notebook iff it contains ``.notebookai/notebook.json``.

Two kinds of roots are scanned:
- ``library_root`` — the canonical home (``~/NotebookAI/notebooks``).
- ``extra_notebook_roots`` — externally registered absolute notebook paths
  read from ``~/NotebookAI/config.json``.
"""

from __future__ import annotations

from notebookai.library.scanner import (
    Library,
    LibraryScanner,
    NotebookEntry,
    load_library_config,
    save_library_config,
)

__all__ = [
    "Library",
    "LibraryScanner",
    "NotebookEntry",
    "load_library_config",
    "save_library_config",
]
