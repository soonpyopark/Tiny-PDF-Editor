#!/usr/bin/env python3
"""Generate transparent branding assets from the source logo image."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "source_logo.png"
OUT_DIR = ROOT / "pdf_editor" / "branding"


def find_source() -> Path:
    if SOURCE.is_file():
        return SOURCE
    raise FileNotFoundError(
        "Source logo not found. Place it at assets/source_logo.png",
    )


def make_transparent_logo(src: Path) -> Image.Image:
    img = Image.open(src).convert("RGBA")
    data = np.array(img)
    height, width = data.shape[:2]

    def is_background(red: int, green: int, blue: int) -> bool:
        return red >= 245 and green >= 245 and blue >= 245

    visited = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height or visited[y, x]:
            continue
        red, green, blue, _alpha = data[y, x]
        if not is_background(red, green, blue):
            continue
        visited[y, x] = True
        data[y, x, 3] = 0
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    alpha = data[:, :, 3]
    rows, cols = np.where(alpha > 0)
    top, bottom = rows.min(), rows.max()
    left, right = cols.min(), cols.max()
    return Image.fromarray(data[top : bottom + 1, left : right + 1])


def main() -> None:
    source = find_source()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    logo = make_transparent_logo(source)
    logo_path = OUT_DIR / "app_logo.png"
    logo.save(logo_path)

    ico_image = logo.copy()
    ico_image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    ico_path = OUT_DIR / "app_icon.ico"
    ico_image.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    print(f"saved {logo_path} ({logo.size[0]}x{logo.size[1]})")
    print(f"saved {ico_path}")


if __name__ == "__main__":
    main()
