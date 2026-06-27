#!/usr/bin/env python3
"""Generate branding assets from the source logo image."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "source_logo.png"
OUT_DIR = ROOT / "pdf_editor" / "branding"

_SATURATION_THRESHOLD = 0.06
_WHITE_BG_THRESHOLD = 232
_ICON_CROP_PADDING = 4
_ICON_CANVAS_BG = (255, 255, 255)


def find_source() -> Path:
    if SOURCE.is_file():
        return SOURCE
    raise FileNotFoundError(
        "Source logo not found. Place it at assets/source_logo.png",
    )


def _is_checkerboard_gray(red: int, green: int, blue: int) -> bool:
    if abs(red - green) > 12 or abs(green - blue) > 12:
        return False
    gray = (red + green + blue) / 3
    return 115 <= gray <= 195


def _opaque_array(image: Image.Image) -> np.ndarray:
    data = np.array(image.convert("RGBA"))
    data[:, :, 3] = 255
    return data


def _crop_alpha(data: np.ndarray, *, padding: int = _ICON_CROP_PADDING) -> Image.Image:
    height, width = data.shape[:2]
    rows, cols = np.where(data[:, :, 3] > 0)
    if len(rows) == 0:
        raise ValueError("Could not detect the inner icon in assets/source_logo.png")

    top = max(0, int(rows.min()) - padding)
    bottom = min(height - 1, int(rows.max()) + padding)
    left = max(0, int(cols.min()) - padding)
    right = min(width - 1, int(cols.max()) + padding)
    return Image.fromarray(data[top : bottom + 1, left : right + 1])


def _saturation_map(data: np.ndarray) -> np.ndarray:
    red = data[:, :, 0].astype(np.float32)
    green = data[:, :, 1].astype(np.float32)
    blue = data[:, :, 2].astype(np.float32)
    max_channel = np.maximum(np.maximum(red, green), blue)
    min_channel = np.minimum(np.minimum(red, green), blue)
    return (max_channel - min_channel) / (max_channel + 1.0)

def _crop_mask(data: np.ndarray, mask: np.ndarray, *, padding: int = _ICON_CROP_PADDING) -> Image.Image:
    output = data.copy()
    output[~mask, 3] = 0
    return _crop_alpha(output, padding=padding)


def _is_preview_background_pixel(red: int, green: int, blue: int) -> bool:
    max_channel = max(red, green, blue)
    min_channel = min(red, green, blue)
    saturation = (max_channel - min_channel) / (max_channel + 1)
    if max_channel <= 50:
        return True
    if (
        abs(red - green) <= 12
        and abs(green - blue) <= 12
        and saturation <= 0.08
        and max_channel <= 190
    ):
        return True
    return False


def _has_preview_background(data: np.ndarray) -> bool:
    edge = np.concatenate(
        [data[0, :, :3], data[-1, :, :3], data[:, 0, :3], data[:, -1, :3]],
    )
    if edge.size == 0:
        return False
    samples = edge.reshape(-1, 3)
    preview = sum(
        1
        for red, green, blue in samples
        if _is_preview_background_pixel(int(red), int(green), int(blue))
    )
    return preview / len(samples) >= 0.4


def _max_channel_map(data: np.ndarray) -> np.ndarray:
    red = data[:, :, 0].astype(np.float32)
    green = data[:, :, 1].astype(np.float32)
    blue = data[:, :, 2].astype(np.float32)
    return np.maximum(np.maximum(red, green), blue)


def extract_preview_background_icon(source: Path) -> Image.Image:
    """Remove baked preview backgrounds (checkerboard/black) from exported PNGs."""
    data = np.array(Image.open(source).convert("RGBA"))
    saturation = _saturation_map(data)
    max_channel = _max_channel_map(data)

    background = _flood_background_mask(
        data,
        is_background=_is_preview_background_pixel,
    )
    keep = ~background
    bounds_mask = keep & ((saturation >= 0.10) | (max_channel >= 180))

    output = data.copy()
    output[:, :, 3] = np.where(keep, 255, 0).astype(np.uint8)

    height, width = data.shape[:2]
    rows, cols = np.where(bounds_mask)
    if len(rows) == 0:
        return _crop_alpha(output)

    pad = _ICON_CROP_PADDING
    top = max(0, int(rows.min()) - pad)
    bottom = min(height - 1, int(rows.max()) + pad)
    left = max(0, int(cols.min()) - pad)
    right = min(width - 1, int(cols.max()) + pad)
    return Image.fromarray(output[top : bottom + 1, left : right + 1])


def _is_white_background_pixel(red: int, green: int, blue: int) -> bool:
    if red >= _WHITE_BG_THRESHOLD and green >= _WHITE_BG_THRESHOLD and blue >= _WHITE_BG_THRESHOLD:
        return True
    brightness = (red + green + blue) / 3
    saturation = (max(red, green, blue) - min(red, green, blue)) / (max(red, green, blue) + 1)
    return brightness >= 218 and saturation <= 0.07


def _flood_background_mask(
    data: np.ndarray,
    *,
    is_background,
) -> np.ndarray:
    height, width = data.shape[:2]
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
        if not is_background(int(red), int(green), int(blue)):
            continue
        visited[y, x] = True
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    return visited


def _edges_are_white(data: np.ndarray, threshold: int = _WHITE_BG_THRESHOLD) -> bool:
    edge = np.concatenate(
        [data[0, :, :3], data[-1, :, :3], data[:, 0, :3], data[:, -1, :3]],
    )
    return bool(edge.size and edge.min() >= threshold)


def _edges_are_checkerboard(data: np.ndarray) -> bool:
    edge = np.concatenate(
        [data[0, :, :3], data[-1, :, :3], data[:, 0, :3], data[:, -1, :3]],
    )
    if edge.size == 0:
        return False
    samples = edge.reshape(-1, 3)
    neutral = 0
    for red, green, blue in samples:
        if _is_checkerboard_gray(int(red), int(green), int(blue)):
            neutral += 1
    return neutral / len(samples) >= 0.6


def extract_white_background_icon(source: Path) -> Image.Image:
    """Remove white canvas and soft drop shadow; keep the orange icon card."""
    data = np.array(Image.open(source).convert("RGBA"))
    saturation = _saturation_map(data)

    background = _flood_background_mask(
        data,
        is_background=_is_white_background_pixel,
    )
    keep = (~background) | (saturation >= _SATURATION_THRESHOLD)

    output = data.copy()
    output[:, :, 3] = np.where(keep, 255, 0).astype(np.uint8)
    return _crop_alpha(output)


def extract_checkerboard_icon(source: Path) -> Image.Image:
    """Remove preview checkerboard and outer glow; keep the icon card."""
    data = np.array(Image.open(source).convert("RGBA"))
    saturation = _saturation_map(data)

    icon_mask = saturation >= _SATURATION_THRESHOLD
    icon_mask &= ~_flood_background_mask(
        data,
        is_background=lambda r, g, b: _is_checkerboard_gray(r, g, b),
    )
    return _crop_mask(data, icon_mask)


def make_transparent_logo(src: Path) -> Image.Image:
    """Legacy path for plain white-fringe PNG sources."""
    img = Image.open(src).convert("RGBA")
    data = np.array(img)
    height, width = data.shape[:2]

    visited = _flood_background_mask(
        data,
        is_background=lambda r, g, b: r >= 245 and g >= 245 and b >= 245,
    )
    cropped = _crop_mask(data, ~visited, padding=0)
    return Image.fromarray(_opaque_array(cropped))


def prepare_logo(source: Path) -> Image.Image:
    img = Image.open(source).convert("RGBA")
    data = np.array(img)

    if _has_preview_background(data):
        return extract_preview_background_icon(source)
    if _edges_are_white(data):
        return extract_white_background_icon(source)
    if _edges_are_checkerboard(data):
        return extract_checkerboard_icon(source)

    edge_alpha = np.concatenate(
        [data[0, :, 3], data[-1, :, 3], data[:, 0, 3], data[:, -1, 3]],
    )
    if edge_alpha.size and edge_alpha.min() < 128:
        cropped = img.crop(img.getbbox() or (0, 0, img.width, img.height))
        return Image.fromarray(_opaque_array(cropped))

    return make_transparent_logo(source)


def make_square_icon(icon: Image.Image, size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (*_ICON_CANVAS_BG, 255))
    fitted = icon.convert("RGBA")
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas.convert("RGB")


def main() -> None:
    source = find_source()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    logo = prepare_logo(source)
    logo_path = OUT_DIR / "app_logo.png"
    logo.save(logo_path)

    icon_png_path = OUT_DIR / "app_icon.png"
    make_square_icon(logo, 256).save(icon_png_path)

    ico_path = OUT_DIR / "app_icon.ico"
    make_square_icon(logo, 256).save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    print(f"saved {logo_path} ({logo.size[0]}x{logo.size[1]})")
    print(f"saved {icon_png_path}")
    print(f"saved {ico_path}")


if __name__ == "__main__":
    main()
