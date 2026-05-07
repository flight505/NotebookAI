# Sidecar binary (PyInstaller)

This directory builds a single-file executable that contains the FastAPI
backend plus an embedded Python runtime, so the Tauri desktop app does not
require `uv` (or any Python install) on the end-user's machine.

## When to rebuild

- Any change to `backend/notebookai/**` source.
- Any change to `backend/pyproject.toml` dependencies.
- Any sentence-transformers / torch / sqlite-vec version bump.

The shipped DMG/MSI/AppImage embeds whatever binary lives in
`desktop/src-tauri/binaries/`. Tauri picks it up automatically when you run
`pnpm tauri:build`.

## How to build (locally)

```bash
# from repo root
cd backend && uv sync                     # pulls pyinstaller (dev dep)
cd ..
uv run --project backend python desktop/sidecar/build.py
```

The script:
1. Detects the host's Rust target triple (e.g. `aarch64-apple-darwin`) by
   shelling out to `rustc -Vv`. Falls back to a hardcoded map if `rustc`
   isn't installed.
2. Runs PyInstaller against `notebookai-api.spec` in `--onefile` mode.
3. Copies the resulting binary to
   `desktop/src-tauri/binaries/notebookai-api-<triple>` — this is exactly
   where Tauri's `bundle.externalBin` lookup expects it.
4. Writes `build-manifest.json` (sha256, size, platform).

Pass `--clean` to force a from-scratch PyInstaller run after any dep upgrade.

## Bundle size

Expect **200-400 MB** uncompressed. The bulk is:

| Library                                  | Approx. |
| ---------------------------------------- | ------: |
| `torch` (CPU only)                       | 150 MB  |
| `sentence-transformers` model wheel deps |  10 MB  |
| `transformers` + `tokenizers`            |  60 MB  |
| Python stdlib + `notebookai`             |  20 MB  |

That's expected for a desktop app that ships an offline embedding model. We
exclude CUDA shims on macOS but cannot strip torch entirely without losing
sentence-transformers.

The actual model weights (~33 MB for `bge-small-en-v1.5`) are NOT bundled —
the first launch downloads them to the user's HuggingFace cache. This keeps
the installer reasonable and lets users swap embedding models via the
`NOTEBOOKAI_EMB_MODEL` env var.

## sqlite-vec extension

`sqlite-vec` ships a loadable shared library (`.dylib`/`.so`/`.dll`) that the
package loads via `sqlite_vec.loadable_path()` at runtime. PyInstaller can't
trace this through static analysis, so the spec file discovers the path at
build time and includes it via `--add-binary`. If the binary is missing,
`IndexStore.bootstrap()` will fail when initializing a notebook.

## Cross-platform

PyInstaller does **not** cross-compile. Each platform must build its own
binary on a matching host. CI handles this via
`.github/workflows/build-sidecar.yml` (matrix over macOS arm64/x64,
Linux x64/arm64, Windows x64).

For local development, just build for your own host and the desktop app will
pick it up.

## macOS notes

The bundled binary is **unsigned**. On first launch from a downloaded DMG the
OS will quarantine the app. Run:

```bash
xattr -dr com.apple.quarantine /Applications/NotebookAI.app
```

A future PR will add codesigning + notarization. Until then, only direct
local builds (`pnpm tauri:build`) work without the dance above.

## Developer fallback

If no sidecar binary is found in `desktop/src-tauri/binaries/`, the Rust
shell falls back to invoking `uv run --project ../../backend notebookai-api`
(see `desktop/src-tauri/src/lib.rs::spawn_backend`). This is the dev-loop
path — no need to rebuild PyInstaller for every backend change.

However, **Tauri's build script requires the externalBin file to exist at
compile time** (`cargo check` will fail otherwise). For first-time setup or
fresh clones, run:

```bash
uv run --project backend python desktop/sidecar/build.py --placeholder
```

This writes a tiny shell-script stub at the expected path that itself
delegates to `uv run`, so the dev-loop is identical to the Phase-12 setup but
both `cargo check` and `pnpm tauri:dev` are happy.
