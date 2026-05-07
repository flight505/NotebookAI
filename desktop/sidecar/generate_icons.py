"""Generate NotebookAI app icons.

Produces a coherent icon set for Tauri (macOS .icns, Windows .ico, Linux PNGs)
and a web favicon. Visual identity: warm cream + ink-blue per the frontend
palette. The mark is a custom 'N' letterform with a single accent node at the
top-right vertical, suggesting both 'notebook' and 'a connected graph of
knowledge'.

Usage:
    cd backend && uv run python ../desktop/sidecar/generate_icons.py

Idempotent — safe to re-run. Writes to:
    desktop/src-tauri/icons/        (Tauri bundle)
    frontend/public/favicon.ico     (web favicon)
    frontend/app/icon.png           (Next.js auto-favicon, 256x256)
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# palette + geometry
# ---------------------------------------------------------------------------

INK_TOP = (42, 74, 107, 255)        # #2a4a6b — frontend accent
INK_BOTTOM = (31, 58, 85, 255)      # #1f3a55 — slightly darker for depth
CREAM = (250, 248, 245, 255)        # #faf8f5 — frontend background
ACCENT = (180, 140, 90, 255)        # warm amber — the "AI node"

# Icon canvas — rendered at 1024 master, then resized for all targets.
MASTER = 1024
PADDING_PCT = 0.16                  # safe area inside the canvas
CORNER_PCT = 0.225                  # rounded-corner radius (Apple superellipse approximation)
NODE_RADIUS_PCT = 0.06              # accent dot at top-right
STROKE_WIDTH_PCT = 0.18             # bar thickness for the N

# All standard sizes required by Tauri + favicons.
PNG_SIZES = [16, 24, 32, 48, 64, 96, 128, 256, 512, 1024]
ICNS_SIZES = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
              (256, 1), (256, 2), (512, 1), (512, 2)]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _vertical_gradient(size: int, top: tuple[int, int, int, int],
                       bottom: tuple[int, int, int, int]) -> Image.Image:
    """Solid vertical gradient on a square canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = round(top[0] * (1 - t) + bottom[0] * t)
        g = round(top[1] * (1 - t) + bottom[1] * t)
        b = round(top[2] * (1 - t) + bottom[2] * t)
        a = round(top[3] * (1 - t) + bottom[3] * t)
        for x in range(size):
            px[x, y] = (r, g, b, a)  # type: ignore[index]
    return img


def _squircle_mask(size: int, radius: int) -> Image.Image:
    """An iOS-style rounded-corner mask (closer to a squircle than a true
    rounded rect by sampling a superellipse with n=5)."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    # Use a high-fidelity superellipse for the canvas shape.
    n = 5.0
    cx, cy = size / 2, size / 2
    a = b = (size / 2) - 1
    pts = []
    steps = max(360, size)
    for i in range(steps + 1):
        theta = (i / steps) * 2 * math.pi
        c, s = math.cos(theta), math.sin(theta)
        x = cx + a * math.copysign(abs(c) ** (2 / n), c)
        y = cy + b * math.copysign(abs(s) ** (2 / n), s)
        pts.append((x, y))
    draw.polygon(pts, fill=255)
    _ = radius  # kept for API stability
    return mask


def render_master() -> Image.Image:
    """Render the 1024×1024 master icon."""
    size = MASTER
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Gradient body, masked to a squircle.
    gradient = _vertical_gradient(size, INK_TOP, INK_BOTTOM)
    mask = _squircle_mask(size, int(size * CORNER_PCT))
    canvas.paste(gradient, (0, 0), mask)

    # Foreground mark: a custom 'N' letterform.
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(fg)

    pad = int(size * PADDING_PCT)
    left = pad
    right = size - pad
    top = pad
    bottom = size - pad
    stroke = int(size * STROKE_WIDTH_PCT)

    # Left vertical bar
    draw.rounded_rectangle(
        [(left, top), (left + stroke, bottom)],
        radius=int(stroke * 0.22),
        fill=CREAM,
    )
    # Right vertical bar
    draw.rounded_rectangle(
        [(right - stroke, top), (right, bottom)],
        radius=int(stroke * 0.22),
        fill=CREAM,
    )

    # Diagonal connector from top-left bar to bottom-right bar.
    # We approximate a thick stroke by drawing a rotated rectangle as a polygon.
    diag_top_left = (left + stroke * 0.05, top + stroke * 0.05)
    diag_top_right = (left + stroke * 0.95, top + stroke * 0.05)
    diag_bot_right = (right - stroke * 0.05, bottom - stroke * 0.05)
    diag_bot_left = (right - stroke * 0.95, bottom - stroke * 0.05)
    draw.polygon(
        [diag_top_left, diag_top_right, diag_bot_right, diag_bot_left],
        fill=CREAM,
    )

    # Accent node — the 'AI dot' floating at the top-right of the N.
    node_r = int(size * NODE_RADIUS_PCT)
    node_cx = right - stroke // 2
    node_cy = top - int(node_r * 0.35)
    # If the node escapes the safe area, nudge it inward.
    if node_cy - node_r < 0:
        node_cy = node_r + int(size * 0.02)
    draw.ellipse(
        [(node_cx - node_r, node_cy - node_r),
         (node_cx + node_r, node_cy + node_r)],
        fill=ACCENT,
    )

    # A subtle hairline from the node down into the right bar — implies
    # a knowledge edge rather than a free-floating dot.
    hair_w = max(2, stroke // 12)
    draw.rectangle(
        [(node_cx - hair_w // 2, node_cy + node_r),
         (node_cx + hair_w // 2, top + stroke // 4)],
        fill=ACCENT,
    )

    # Mask the foreground to the same squircle so nothing escapes.
    fg_masked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fg_masked.paste(fg, (0, 0), mask)
    canvas.alpha_composite(fg_masked)

    return canvas


# ---------------------------------------------------------------------------
# format writers
# ---------------------------------------------------------------------------


def write_pngs(master: Image.Image, out_dir: Path) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    for size in PNG_SIZES:
        img = master.resize((size, size), Image.LANCZOS)
        # Tauri's expected naming convention.
        name = "icon.png" if size == master.size[0] else f"{size}x{size}.png"
        path = out_dir / name
        img.save(path, "PNG", optimize=True)
        paths[size] = path
    # Tauri also wants @2x retina for 128.
    img128_2x = master.resize((256, 256), Image.LANCZOS)
    img128_2x.save(out_dir / "128x128@2x.png", "PNG", optimize=True)
    return paths


def write_icns(master: Image.Image, path: Path) -> None:
    """Write a macOS .icns containing every Apple-required size.

    Pillow's ICNS writer is fine for the standard sizes; we hand a list
    of pre-resized images keyed by Apple's OSType codes via the `sizes`
    parameter.
    """
    # Pillow expects a single base image; it generates the per-size variants
    # internally based on the `sizes` keyword. Ensure base is square + RGBA.
    images = []
    for size, scale in ICNS_SIZES:
        actual = size * scale
        img = master.resize((actual, actual), Image.LANCZOS)
        images.append(img)
    # Save as ICNS using the largest source.
    largest = max(images, key=lambda i: i.size[0])
    largest.save(path, format="ICNS")


def write_ico(master: Image.Image, path: Path) -> None:
    """Windows .ico with multiple sizes embedded."""
    sizes = [(s, s) for s in ICO_SIZES]
    master.save(path, format="ICO", sizes=sizes)


def write_favicon(master: Image.Image, path: Path) -> None:
    """Browser favicon — multi-size .ico."""
    write_ico(master, path)


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    icons_dir = repo / "desktop" / "src-tauri" / "icons"
    favicon_dst = repo / "frontend" / "public" / "favicon.ico"
    nextjs_icon_dst = repo / "frontend" / "app" / "icon.png"

    print("rendering master 1024x1024...")
    master = render_master()

    print(f"writing PNGs to {icons_dir}/")
    pngs = write_pngs(master, icons_dir)
    for size, p in sorted(pngs.items()):
        print(f"  {size}x{size}: {p.name}")

    icns_path = icons_dir / "icon.icns"
    print(f"writing macOS icon: {icns_path}")
    write_icns(master, icns_path)

    ico_path = icons_dir / "icon.ico"
    print(f"writing Windows icon: {ico_path}")
    write_ico(master, ico_path)

    favicon_dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing web favicon: {favicon_dst}")
    write_favicon(master, favicon_dst)

    nextjs_icon_dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing Next.js app icon: {nextjs_icon_dst}")
    master.resize((512, 512), Image.LANCZOS).save(nextjs_icon_dst, "PNG", optimize=True)

    # Stash a high-res branding asset that docs can use.
    brand_dst = repo / "docs" / "img" / "icon.png"
    brand_dst.parent.mkdir(parents=True, exist_ok=True)
    master.save(brand_dst, "PNG", optimize=True)
    print(f"writing 1024 branding asset: {brand_dst}")

    print("done.")


if __name__ == "__main__":
    main()


# Suppress unused-import warning if the file is run as a script.
_ = struct
