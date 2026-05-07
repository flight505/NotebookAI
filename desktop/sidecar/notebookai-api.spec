# PyInstaller spec for the NotebookAI FastAPI sidecar.
#
# Driven by build.py — running `pyinstaller notebookai-api.spec` directly works
# too, but build.py adds platform/arch detection and writes the binary to the
# location Tauri expects (`desktop/src-tauri/binaries/notebookai-api-<triple>`).
#
# Bundle size note: sentence-transformers + torch are ~150-300MB on disk.
# That's the cost of an offline-capable embedding model. We exclude CUDA on
# macOS where it will never run.

# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# ---------------------------------------------------------------------------
# Locate the backend source tree relative to the spec file.
# ---------------------------------------------------------------------------
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
NOTEBOOKAI_PKG = BACKEND_DIR / "notebookai"

if not NOTEBOOKAI_PKG.is_dir():
    raise SystemExit(
        f"notebookai package not found at {NOTEBOOKAI_PKG} — run from repo root"
    )

# ---------------------------------------------------------------------------
# sqlite-vec ships a loadable extension (.dylib/.so/.dll) that PyInstaller's
# dependency analyzer never sees because it's loaded via ctypes at runtime.
# Discover the path at build time and add it as a binary so the frozen app
# can still call ``sqlite_vec.load(conn)``.
# ---------------------------------------------------------------------------
sqlite_vec_binaries: list[tuple[str, str]] = []
try:
    import sqlite_vec  # type: ignore[import-not-found]

    # loadable_path() returns the stem (e.g. .../vec0); sqlite3 appends the
    # platform extension (.dylib/.so/.dll) at load time. Resolve the real file.
    stem = Path(sqlite_vec.loadable_path())
    candidates = [stem] + [stem.with_suffix(ext) for ext in (".dylib", ".so", ".dll")]
    vec_path = next((p for p in candidates if p.exists() and p.is_file()), None)
    if vec_path is None:
        print(
            f"[notebookai-api.spec] warning: no loadable sqlite_vec extension found "
            f"among {[str(p) for p in candidates]}"
        )
    else:
        # (src, dest_dir_inside_bundle) — keep it inside the package dir so
        # ``sqlite_vec.loadable_path()`` resolves correctly at runtime.
        sqlite_vec_binaries.append((str(vec_path), "sqlite_vec"))
except Exception as exc:  # pragma: no cover - best-effort during build
    print(f"[notebookai-api.spec] warning: sqlite_vec discovery failed: {exc}")

# ---------------------------------------------------------------------------
# Collect data + hidden imports for libraries that PyInstaller can't trace
# statically (sentence-transformers loads modules dynamically at runtime).
# ---------------------------------------------------------------------------
hidden_imports: list[str] = [
    "notebookai",
    "notebookai.api",
    "notebookai.api.app",
    "notebookai.api.main",
    "notebookai.config",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sentence_transformers",
    "transformers",
    "torch",
    "sqlite_vec",
    "sqlalchemy.dialects.sqlite",
]

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = list(sqlite_vec_binaries)

for pkg in ("sentence_transformers", "transformers", "tokenizers", "huggingface_hub"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas.extend(pkg_datas)
        binaries.extend(pkg_binaries)
        hidden_imports.extend(pkg_hidden)
    except Exception as exc:  # pragma: no cover
        print(f"[notebookai-api.spec] warning: collect_all({pkg!r}) failed: {exc}")

# certifi for https on frozen Python (httpx, huggingface_hub)
try:
    datas.extend(collect_data_files("certifi"))
    hidden_imports.append("certifi")
except Exception:  # pragma: no cover
    pass

# Exclude things we know we don't need to keep the bundle slimmer.
excludes: list[str] = [
    "tkinter",
    "matplotlib",
    "PIL.ImageTk",
    "IPython",
    "jupyter",
    "pytest",
]
if sys.platform == "darwin":
    # No CUDA on Mac. PyInstaller still picks up some torch CUDA shims; drop them.
    excludes.extend(["torch.cuda", "torch.backends.cuda", "torch.backends.cudnn"])

# ---------------------------------------------------------------------------
# Entry point — a tiny shim that imports + calls notebookai.api.main:run.
# ---------------------------------------------------------------------------
entry_script = SPEC_DIR / "_entry.py"
entry_script.write_text(
    "from __future__ import annotations\n"
    "import multiprocessing\n"
    "import sys\n"
    "from notebookai.api.main import run\n"
    "if __name__ == '__main__':\n"
    "    multiprocessing.freeze_support()\n"
    "    sys.exit(run() or 0)\n",
    encoding="utf-8",
)

a = Analysis(
    [str(entry_script)],
    pathex=[str(BACKEND_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="notebookai-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX often breaks signed/notarized macOS binaries
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # let PyInstaller match the host
    codesign_identity=None,
    entitlements_file=None,
)
