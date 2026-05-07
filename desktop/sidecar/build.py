"""Build the PyInstaller sidecar binary for the Tauri desktop app.

Usage
-----
    cd <repo-root>
    uv run --project backend python desktop/sidecar/build.py

What it does
------------
1. Resolves the host platform/arch and the matching Rust target triple
   (Tauri's sidecar lookup is `<name>-<triple>`).
2. Invokes PyInstaller against ``notebookai-api.spec``.
3. Copies the produced binary to
   ``desktop/src-tauri/binaries/notebookai-api-<triple>``.
4. Writes a small ``build-manifest.json`` with size, sha256, and platform info
   so CI can attach it to a release.

Cross-compilation is NOT supported. Each platform builds its own binary;
GitHub Actions (`.github/workflows/build-sidecar.yml`) runs the matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SPEC_NAME = "notebookai-api.spec"
BINARY_NAME = "notebookai-api"

# Map ``(system, machine)`` to the canonical Rust target triple Tauri uses to
# locate the sidecar at runtime. Tauri appends the triple, so the file on disk
# must be named ``notebookai-api-<triple>`` (with ``.exe`` on Windows).
RUST_TARGET_TRIPLES: dict[tuple[str, str], str] = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Linux", "arm64"): "aarch64-unknown-linux-gnu",
    ("Windows", "AMD64"): "x86_64-pc-windows-msvc",
    ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Windows", "ARM64"): "aarch64-pc-windows-msvc",
}


def detect_target_triple() -> str:
    """Return the Rust target triple of the host, preferring ``rustc -Vv``."""
    rustc = shutil.which("rustc")
    if rustc:
        try:
            out = subprocess.check_output([rustc, "-Vv"], text=True, timeout=10)
            for line in out.splitlines():
                if line.startswith("host:"):
                    return line.split(":", 1)[1].strip()
        except (subprocess.SubprocessError, OSError):
            pass
    key = (platform.system(), platform.machine())
    if key not in RUST_TARGET_TRIPLES:
        raise SystemExit(f"unsupported host platform/arch: {key}")
    return RUST_TARGET_TRIPLES[key]


def find_pyinstaller() -> list[str]:
    """Return the command to invoke PyInstaller."""
    pyi = shutil.which("pyinstaller")
    if pyi:
        return [pyi]
    return [sys.executable, "-m", "PyInstaller"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_placeholder() -> int:
    """Write a tiny stub at the Tauri-expected path so cargo check succeeds.

    The stub just delegates to ``uv run`` — same fallback path the Rust shell
    uses when the bundled sidecar is missing — so a developer can iterate on
    the desktop app without waiting for PyInstaller. Real builds replace it.
    """
    sidecar_dir = Path(__file__).resolve().parent
    triple = detect_target_triple()
    suffix = ".exe" if platform.system() == "Windows" else ""
    tauri_bin_dir = sidecar_dir.parent / "src-tauri" / "binaries"
    tauri_bin_dir.mkdir(parents=True, exist_ok=True)
    target = tauri_bin_dir / f"{BINARY_NAME}-{triple}{suffix}"

    if platform.system() == "Windows":
        body = (
            "@echo off\r\n"
            "echo [notebookai-api] placeholder sidecar; using `uv run` fallback >&2\r\n"
            'uv run --project "%~dp0..\\..\\..\\backend" notebookai-api %*\r\n'
        )
    else:
        body = (
            "#!/bin/sh\n"
            "echo '[notebookai-api] placeholder sidecar; using uv run fallback' >&2\n"
            'exec uv run --project "$(dirname "$0")/../../../backend" '
            'notebookai-api "$@"\n'
        )
    target.write_text(body, encoding="utf-8")
    if platform.system() != "Windows":
        target.chmod(0o755)
    print(f"[build.py] wrote placeholder sidecar -> {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Pass --clean to PyInstaller (slower; required after dep upgrades).",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Skip the copy into desktop/src-tauri/binaries (useful for local debugging).",
    )
    parser.add_argument(
        "--placeholder",
        action="store_true",
        help=(
            "Skip PyInstaller; just write a thin shell stub at the path Tauri "
            "expects so `cargo check` / `pnpm tauri:dev` succeed. The runtime "
            "shell falls back to `uv run` anyway, so this is the developer-loop "
            "shortcut — no need to wait 5-10 min for a real build."
        ),
    )
    args = parser.parse_args()

    if args.placeholder:
        return _write_placeholder()

    sidecar_dir = Path(__file__).resolve().parent
    spec = sidecar_dir / SPEC_NAME
    if not spec.is_file():
        raise SystemExit(f"spec file not found: {spec}")

    triple = detect_target_triple()
    print(f"[build.py] host triple: {triple}")

    cmd = [
        *find_pyinstaller(),
        "--noconfirm",
        "--distpath",
        str(sidecar_dir / "dist"),
        "--workpath",
        str(sidecar_dir / "build"),
        str(spec),
    ]
    if args.clean:
        cmd.insert(-1, "--clean")

    print(f"[build.py] running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    suffix = ".exe" if platform.system() == "Windows" else ""
    built = sidecar_dir / "dist" / f"{BINARY_NAME}{suffix}"
    if not built.is_file():
        raise SystemExit(f"PyInstaller did not produce {built}")

    target_path = sidecar_dir / "dist" / f"{BINARY_NAME}-{triple}{suffix}"
    if built != target_path:
        shutil.copy2(built, target_path)

    if not args.no_copy:
        tauri_bin_dir = sidecar_dir.parent / "src-tauri" / "binaries"
        tauri_bin_dir.mkdir(parents=True, exist_ok=True)
        deployed = tauri_bin_dir / f"{BINARY_NAME}-{triple}{suffix}"
        shutil.copy2(built, deployed)
        # Tauri requires the sidecar to be executable; preserve mode on POSIX.
        if platform.system() != "Windows":
            deployed.chmod(0o755)
        print(f"[build.py] deployed sidecar -> {deployed}")

    size = built.stat().st_size
    digest = sha256_of(built)
    manifest = {
        "name": BINARY_NAME,
        "triple": triple,
        "platform": platform.system(),
        "machine": platform.machine(),
        "filename": target_path.name,
        "bytes": size,
        "size_mb": round(size / (1024 * 1024), 2),
        "sha256": digest,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
    }
    manifest_path = sidecar_dir / "build-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"[build.py] {target_path.name}: {manifest['size_mb']} MB, sha256={digest[:12]}…"
    )
    print(f"[build.py] manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
