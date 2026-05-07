"""Tests guarding the PyInstaller-bundled sidecar entry point.

Two contracts protect the frozen binary path:

1. ``notebookai.api.main.run`` must call ``uvicorn.run`` with ``reload=False``
   regardless of frozen state, but it MUST also tolerate ``sys.frozen=True``
   without crashing (i.e. ``multiprocessing.freeze_support`` is invoked once,
   not on every regular dev invocation).
2. ``sqlite_vec.loadable_path()`` must point at a real file at build time,
   because PyInstaller can't trace the ctypes-loaded extension and we add it
   via ``--add-binary`` in ``notebookai-api.spec``.

Neither test actually invokes pyinstaller — the bundle is verified by
``.github/workflows/build-sidecar.yml``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from notebookai.api import main as api_main


def test_main_run_no_reload_in_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """When sys.frozen is set, uvicorn.run must not be called with reload=True."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    fake_uvicorn = MagicMock()
    fake_uvicorn.run = MagicMock()
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    with patch("multiprocessing.freeze_support") as freeze_support:
        api_main.run()

    # freeze_support is critical in frozen mode to prevent worker recursion.
    freeze_support.assert_called_once()

    fake_uvicorn.run.assert_called_once()
    _, kwargs = fake_uvicorn.run.call_args
    assert kwargs.get("reload") is False, (
        "uvicorn must run with reload=False in frozen mode; "
        f"got reload={kwargs.get('reload')!r}"
    )
    assert kwargs.get("factory") is True
    assert kwargs.get("host")
    assert kwargs.get("port")


def test_main_run_no_freeze_support_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """In normal dev (sys.frozen unset), freeze_support must NOT be called."""
    monkeypatch.delattr(sys, "frozen", raising=False)

    fake_uvicorn = MagicMock()
    fake_uvicorn.run = MagicMock()
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    with patch("multiprocessing.freeze_support") as freeze_support:
        api_main.run()

    freeze_support.assert_not_called()
    fake_uvicorn.run.assert_called_once()
    _, kwargs = fake_uvicorn.run.call_args
    assert kwargs.get("reload") is False


def test_sqlite_vec_path_discoverable() -> None:
    """The loadable extension must exist on disk so PyInstaller can bundle it.

    ``sqlite_vec.loadable_path()`` returns a stem (e.g. ``.../vec0``); sqlite3
    appends the platform-specific extension (``.dylib`` / ``.so`` / ``.dll``)
    at load time. The PyInstaller spec resolves the actual file so we make
    sure at least one of the candidate suffixes exists here.
    """
    sqlite_vec = pytest.importorskip("sqlite_vec")
    stem = Path(sqlite_vec.loadable_path())
    candidates = [stem, *(stem.with_suffix(ext) for ext in (".dylib", ".so", ".dll"))]
    found = next((p for p in candidates if p.exists() and p.is_file()), None)
    assert found is not None, (
        f"none of {[str(p) for p in candidates]} exist; the PyInstaller spec "
        "relies on the loadable extension to bundle sqlite-vec."
    )
