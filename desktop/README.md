# NotebookAI Desktop (Tauri 2)

A native desktop shell that wraps the Next.js frontend in a Tauri 2 webview and launches the FastAPI backend as a sidecar process.

## Quick start

```bash
# from repo root
cd desktop
pnpm install
pnpm tauri:dev
```

`pnpm tauri:dev`:
1. Tauri runs `cd ../../frontend && pnpm dev` (Next.js dev server on :3000)
2. Tauri compiles the Rust shell and opens the main window
3. The shell looks up the bundled PyInstaller sidecar; if not present, it falls back to `uv run --project ../../backend notebookai-api` on `127.0.0.1:8765`
4. Once `/healthz` returns 200, the window is shown and a `notebookai-ready` event is emitted

## Backend sidecar

For end-user installers we ship a single-file PyInstaller binary so users don't need `uv` (or any Python install). For local development, the Rust shell automatically falls back to `uv run` when no bundled binary is found.

- **Pre-built binaries** are downloaded from the GitHub Release on tag push (see `.github/workflows/build-sidecar.yml`).
- **To build locally** (e.g. before `pnpm tauri:build`):

  ```bash
  uv run --project ../backend python sidecar/build.py
  ```

  Output lands at `src-tauri/binaries/notebookai-api-<rust-target-triple>` — exactly where Tauri's `bundle.externalBin` looks. See `sidecar/README.md` for size expectations (200-400 MB) and per-platform notes.

- On macOS the binary is currently **unsigned**; first launch from a downloaded DMG requires `xattr -dr com.apple.quarantine /Applications/NotebookAI.app`.

## Production builds

```bash
pnpm tauri:build           # release build for the host platform
pnpm tauri:build:debug     # debug build (faster compile)
```

The `beforeBuildCommand` invokes `pnpm build:tauri` in `frontend/`, which sets `TAURI_BUILD=true` and switches `next.config.ts` to `output: "export"`. Static export lands in `frontend/out/` and Tauri bundles it as the `frontendDist`.

Bundle targets configured in `tauri.conf.json`:
- macOS: `app`, `dmg`
- Linux: `deb`, `appimage`
- Windows: `nsis`, `msi`

## Architecture

```
+----------------------------------+
|  Tauri main window (webview)     |
|   - Next.js static export OR     |
|   - http://localhost:3000 (dev)  |
+----------------------------------+
              | HTTP / WS
              v
+----------------------------------+
|  FastAPI sidecar (uv run)        |
|  127.0.0.1:8765                  |
+----------------------------------+
```

- The frontend talks to the backend via plain HTTP, identical to running `pnpm dev` against a separately-launched backend. The CSP in `tauri.conf.json` allows only `connect-src` to `localhost:8765`.
- The Rust shell exposes a single `backend_url` Tauri command for sanity, but the frontend does not need it.

## Sidecar history

Phase 12 shipped without a bundled Python — the Rust shell shelled out to the user's `uv`. v0.2 introduced the PyInstaller bundle (see "Backend sidecar" above). The dev-loop fallback to `uv run` is preserved so you don't need to rebuild PyInstaller for every backend change; install `uv` (`brew install uv` or https://docs.astral.sh/uv/) if you don't have it.

## Vibrancy / window chrome

- macOS: `decorations: false`, `transparent: true`, `titleBarStyle: "Overlay"`, `hiddenTitle: true`. The Rust shell calls `set_effects` with `Effect::Sidebar` once the window is ready, giving the standard macOS sidebar vibrancy.
- Linux: transparency works on most compositors but is best-effort under Wayland — falls back to a solid frontend background.
- Windows: transparent titlebar with no native vibrancy in this phase.

## Window-close behavior

Closing the main window on macOS hides it (Cmd-W); the app keeps running in the dock. Quit via `Cmd-Q` or right-click the dock icon. Linux/Windows close behaves normally.

## Files

- `package.json` — pnpm workspace root with `@tauri-apps/cli`
- `src-tauri/Cargo.toml` — Tauri 2, shell + fs plugins
- `src-tauri/tauri.conf.json` — window config, CSP, bundle targets
- `src-tauri/src/main.rs` — entrypoint
- `src-tauri/src/lib.rs` — sidecar spawn, health probe, vibrancy, close handler
- `src-tauri/build.rs` — Tauri build script
- `src-tauri/capabilities/default.json` — permissions for the main window
- `src-tauri/icons/` — placeholder icons (replace with branded artwork before release)

## Known issues

- Wayland transparent windows can show black borders on some compositors.
- The first `cargo check` / `cargo build` pulls down ~300 crates and takes 5+ minutes on a clean machine.
- Bundled placeholder icons are dark blue squares with "NA" — swap for real artwork before publishing.
