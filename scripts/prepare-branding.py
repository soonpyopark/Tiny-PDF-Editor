#!/usr/bin/env python3
"""Generate branding assets from the source logo image."""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "source_logo.png"
OUT_DIR = ROOT / "pdf_editor" / "branding"
ICON_OVERRIDES_DIR = ROOT / "assets" / "icon_overrides"
ICON_CHECK_DIR = ROOT / ".cache" / "icon_check"

_SATURATION_THRESHOLD = 0.06
_WHITE_BG_THRESHOLD = 232
_ICON_CROP_PADDING = 4

_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


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
        # Keep existing transparency (e.g. rounded-corner app icons).
        return cropped.convert("RGBA")

    return make_transparent_logo(source)


def fit_icon_png(icon: Image.Image, max_size: int = 256) -> Image.Image:
    """Resize for app_icon.png while preserving transparency like app_logo.png."""
    fitted = icon.convert("RGBA")
    fitted.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return fitted


def make_ico_image(icon: Image.Image, size: int = 256) -> Image.Image:
    """Center icon on a transparent square canvas for .ico export."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fitted = icon.convert("RGBA")
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas


def build_size_images(
    color_icon: Image.Image,
    sizes: tuple[int, ...] = _ICO_SIZES,
) -> list[Image.Image]:
    """Build per-size RGBA images from the color logo for every ICO size."""
    return [make_ico_image(color_icon, size) for size in sizes]


def _parse_size_from_name(name: str, prefixes: tuple[str, ...]) -> int | None:
    stem = Path(name).stem
    for prefix in prefixes:
        marker = f"{prefix}_"
        if not stem.startswith(marker):
            continue
        rest = stem[len(marker) :]
        if "x" not in rest:
            return None
        width_text, height_text = rest.split("x", 1)
        if not width_text.isdigit() or not height_text.isdigit():
            return None
        width, height = int(width_text), int(height_text)
        if width == height:
            return width
    return None


def sync_modified_icon_check_overrides() -> list[str]:
    """Copy user-edited size PNGs from .cache/icon_check into assets/icon_overrides.

    A file is treated as edited when its mtime is at least one day newer than
    the oldest same-family extract in icon_check (original batch vs later edits).
    """
    if not ICON_CHECK_DIR.is_dir():
        return []

    families = {
        "app_icon": ("app_icon", "exe_png"),
        "pdf_file_icon": ("pdf_file_icon",),
    }
    copied: list[str] = []
    ICON_OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)

    for dest_prefix, source_prefixes in families.items():
        candidates: list[Path] = []
        for prefix in source_prefixes:
            candidates.extend(ICON_CHECK_DIR.glob(f"{prefix}_*x*.png"))
        if not candidates:
            continue
        baseline = min(path.stat().st_mtime for path in candidates)
        # Prefer explicit app_icon_* over exe_png_* when both edited for a size.
        by_size: dict[int, Path] = {}
        for path in sorted(candidates, key=lambda item: item.stat().st_mtime):
            if path.stat().st_mtime < baseline + 86400:
                continue
            size = _parse_size_from_name(path.name, source_prefixes)
            if size is None or size not in _ICO_SIZES:
                continue
            # Later mtime wins; app_icon_* sorts after exe_png alphabetically
            # but we sort by mtime above — if same-day edits, prefer app_icon.
            existing = by_size.get(size)
            if existing is not None and existing.name.startswith("app_icon_"):
                if not path.name.startswith("app_icon_"):
                    continue
            by_size[size] = path

        for size, source in sorted(by_size.items()):
            dest = ICON_OVERRIDES_DIR / f"{dest_prefix}_{size}x{size}.png"
            dest.write_bytes(source.read_bytes())
            # Preserve the edit timestamp for later audits.
            mtime = source.stat().st_mtime
            os.utime(dest, (mtime, mtime))
            copied.append(dest.name)

    return copied


def load_size_overrides(prefix: str) -> dict[int, Image.Image]:
    """Load per-size RGBA overrides from assets/icon_overrides."""
    overrides: dict[int, Image.Image] = {}
    if not ICON_OVERRIDES_DIR.is_dir():
        return overrides
    for path in ICON_OVERRIDES_DIR.glob(f"{prefix}_*x*.png"):
        size = _parse_size_from_name(path.name, (prefix,))
        if size is None or size not in _ICO_SIZES:
            continue
        image = Image.open(path).convert("RGBA")
        if image.size != (size, size):
            fitted = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            scaled = image.copy()
            scaled.thumbnail((size, size), Image.Resampling.LANCZOS)
            x = (size - scaled.width) // 2
            y = (size - scaled.height) // 2
            fitted.paste(scaled, (x, y), scaled)
            image = fitted
        overrides[size] = image
    return overrides


def apply_size_overrides(
    images: list[Image.Image],
    overrides: dict[int, Image.Image],
    sizes: tuple[int, ...] = _ICO_SIZES,
) -> tuple[list[Image.Image], list[int]]:
    """Replace generated size bitmaps with override images when present."""
    applied: list[int] = []
    merged: list[Image.Image] = []
    for image, size in zip(images, sizes, strict=True):
        override = overrides.get(size)
        if override is not None:
            merged.append(override)
            applied.append(size)
        else:
            merged.append(image)
    return merged, applied


def save_multi_size_ico(path: Path, images: list[Image.Image]) -> None:
    """Write an .ico containing each pre-rendered size bitmap."""
    if not images:
        raise ValueError("No icon images to save")
    # Pillow's ICO writer expects the largest bitmap first.
    ordered = sorted(images, key=lambda image: image.width * image.height, reverse=True)
    ordered[0].save(
        path,
        format="ICO",
        sizes=[(image.width, image.height) for image in ordered],
        append_images=ordered[1:],
    )


def main() -> None:
    source = find_source()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    synced = sync_modified_icon_check_overrides()
    if synced:
        print("synced icon overrides from .cache/icon_check: " + ", ".join(synced))

    logo = prepare_logo(source)
    logo_path = OUT_DIR / "app_logo.png"
    logo.save(logo_path)

    icon_png_path = OUT_DIR / "app_icon.png"
    app_overrides = load_size_overrides("app_icon")
    if 256 in app_overrides:
        app_overrides[256].save(icon_png_path)
    else:
        fit_icon_png(logo, 256).save(icon_png_path)

    # Transparent rounded icon for app + PDF shell association.
    app_images = build_size_images(logo)
    app_images, app_applied = apply_size_overrides(app_images, app_overrides)
    ico_path = OUT_DIR / "app_icon.ico"
    save_multi_size_ico(ico_path, app_images)

    pdf_images = build_size_images(logo)
    pdf_overrides = load_size_overrides("pdf_file_icon")
    pdf_images, pdf_applied = apply_size_overrides(pdf_images, pdf_overrides)
    pdf_file_icon_path = OUT_DIR / "pdf_file_icon.ico"
    save_multi_size_ico(pdf_file_icon_path, pdf_images)

    print(f"saved {logo_path} ({logo.size[0]}x{logo.size[1]})")
    print(f"saved {icon_png_path}")
    print(f"saved {ico_path} ({len(app_images)} sizes)")
    print(f"saved {pdf_file_icon_path} ({len(pdf_images)} sizes)")
    if app_applied:
        print("app_icon overrides: " + ", ".join(str(size) for size in app_applied))
    if pdf_applied:
        print(
            "pdf_file_icon overrides: "
            + ", ".join(str(size) for size in pdf_applied)
        )


if __name__ == "__main__":
    main()
