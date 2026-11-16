"""Signature stamp helpers: white knockout, ink reinforcement and page placement rects."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pymupdf as fitz
import numpy as np

DEFAULT_WIDTH_RATIO = 0.22
MAX_HEIGHT_RATIO = 0.35
MIN_STAMP_POINTS = 16.0
WHITE_THRESHOLD = 236
FADE_START = 198
MAX_CHROMA = 24
SIGNATURE_ANNOT_TITLE = "tpe:sig"
SIGNATURE_EMBFILE_PREFIX = "tpe-sig-"


@dataclass(frozen=True)
class StampPlacementMemory:
    width_ratio: float
    right_margin_ratio: float
    bottom_margin_ratio: float


@dataclass(frozen=True)
class SignatureStampHit:
    page_index: int
    annot_xref: int
    image_id: str
    rect: fitz.Rect
    width: int
    height: int
    png_bytes: bytes
    image_xref: int | None


def signature_image_id(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()[:16]


def signature_embfile_name(image_id: str) -> str:
    return f"{SIGNATURE_EMBFILE_PREFIX}{image_id}.png"


def is_signature_annot(annot) -> bool:
    title = ((annot.info or {}).get("title") or "").strip()
    return title == SIGNATURE_ANNOT_TITLE


def serialize_signature_annot(image_id: str, width: int, height: int, image_xref: int | None) -> str:
    xref = "" if image_xref is None else str(int(image_xref))
    return f"id={image_id};w={int(width)};h={int(height)};xref={xref}"


def parse_signature_annot(content: str) -> tuple[str, int, int, int | None] | None:
    values: dict[str, str] = {}
    for part in (content or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key.strip()] = value.strip()
    image_id = values.get("id") or ""
    if not image_id:
        return None
    try:
        width = max(1, int(values.get("w") or "1"))
        height = max(1, int(values.get("h") or "1"))
    except ValueError:
        return None
    raw_xref = values.get("xref") or ""
    image_xref: int | None
    try:
        image_xref = int(raw_xref) if raw_xref else None
    except ValueError:
        image_xref = None
    return image_id, width, height, image_xref


def knockout_white_rgba(
    rgba: np.ndarray,
    *,
    white_threshold: int = WHITE_THRESHOLD,
    fade_start: int = FADE_START,
    max_chroma: int = MAX_CHROMA,
) -> np.ndarray:
    """Make near-white paper pixels transparent; keep ink and existing alpha."""
    out = np.array(rgba, copy=True)
    if out.ndim != 3 or out.shape[2] < 4:
        raise ValueError("RGBA image required")
    rgb = out[:, :, :3].astype(np.int32)
    alpha = out[:, :, 3].astype(np.int32)
    luma = (299 * rgb[:, :, 0] + 587 * rgb[:, :, 1] + 114 * rgb[:, :, 2]) // 1000
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    paperish = chroma <= max_chroma
    kill = paperish & (luma >= white_threshold)
    out[:, :, 3] = np.where(kill, 0, out[:, :, 3])
    fade = paperish & (luma >= fade_start) & (luma < white_threshold) & ~kill
    span = max(1, white_threshold - fade_start)
    fade_factor = (white_threshold - luma).astype(np.float32) / span
    faded = np.clip(alpha.astype(np.float32) * fade_factor, 0, 255).astype(np.uint8)
    out[:, :, 3] = np.where(fade, np.minimum(out[:, :, 3], faded), out[:, :, 3])
    return out


def reinforce_signature_ink(rgba: np.ndarray) -> np.ndarray:
    """Darken gray pencil/scan ink so the stamp stays visible after the overlay border is gone."""
    out = np.array(rgba, copy=True)
    if out.ndim != 3 or out.shape[2] < 4:
        return out
    rgb = out[:, :, :3].astype(np.int32)
    alpha = out[:, :, 3]
    luma = (299 * rgb[:, :, 0] + 587 * rgb[:, :, 1] + 114 * rgb[:, :, 2]) // 1000
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    # Gray-ish strokes that survived knockout but are still too light on white paper.
    soft = (alpha >= 40) & (chroma <= MAX_CHROMA) & (luma >= 40) & (luma < WHITE_THRESHOLD)
    if not np.any(soft):
        return out
    # Pull toward black; keep a little of the original tone.
    factor = np.clip((luma.astype(np.float32) - 40.0) / 200.0, 0.15, 0.55)
    strengthened = (rgb.astype(np.float32) * factor[:, :, None]).astype(np.uint8)
    for channel in range(3):
        plane = out[:, :, channel]
        plane = np.where(soft, strengthened[:, :, channel], plane)
        out[:, :, channel] = plane
    # Boost thin/faint alpha so strokes do not disappear after rasterize.
    thin = soft & (alpha < 200)
    out[:, :, 3] = np.where(thin, np.maximum(alpha, 220), out[:, :, 3])
    return out


def crop_alpha_bbox(rgba: np.ndarray, *, alpha_min: int = 8, pad: int = 1) -> np.ndarray | None:
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha > alpha_min)
    if ys.size == 0:
        return None
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    height, width = rgba.shape[:2]
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(height, y1 + pad)
    x1 = min(width, x1 + pad)
    return rgba[y0:y1, x0:x1]


def clamp_rect_to_page(rect: fitz.Rect, page: fitz.Rect) -> fitz.Rect:
    width = float(rect.width)
    height = float(rect.height)
    if width <= 0 or height <= 0 or page.is_empty:
        return fitz.Rect(page.x0, page.y0, page.x0 + 1, page.y0 + 1)
    if width > page.width or height > page.height:
        scale = min(page.width / width, page.height / height)
        width *= scale
        height *= scale
    x0 = min(max(float(rect.x0), float(page.x0)), float(page.x1) - width)
    y0 = min(max(float(rect.y0), float(page.y0)), float(page.y1) - height)
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _stamp_size_on_page(
    page: fitz.Rect,
    image_width: int,
    image_height: int,
    width_ratio: float = DEFAULT_WIDTH_RATIO,
) -> tuple[float, float]:
    aspect = _image_aspect(image_width, image_height)
    dest_w = min(page.width * width_ratio, page.width * 0.9)
    dest_h = dest_w / aspect
    max_h = page.height * MAX_HEIGHT_RATIO
    if dest_h > max_h:
        dest_h = max_h
        dest_w = dest_h * aspect
    dest_w = max(MIN_STAMP_POINTS, dest_w)
    dest_h = dest_w / aspect
    return dest_w, dest_h


def default_stamp_rect(
    page: fitz.Rect,
    image_width: int,
    image_height: int,
    center: fitz.Point,
    *,
    width_ratio: float = DEFAULT_WIDTH_RATIO,
) -> fitz.Rect:
    dest_w, dest_h = _stamp_size_on_page(page, image_width, image_height, width_ratio)
    rect = fitz.Rect(
        center.x - dest_w / 2,
        center.y - dest_h / 2,
        center.x + dest_w / 2,
        center.y + dest_h / 2,
    )
    return clamp_rect_to_page(rect, page)


def bottom_right_stamp_rect(
    page: fitz.Rect,
    image_width: int,
    image_height: int,
    *,
    width_ratio: float = DEFAULT_WIDTH_RATIO,
    margin_ratio: float = 0.04,
) -> fitz.Rect:
    dest_w, dest_h = _stamp_size_on_page(page, image_width, image_height, width_ratio)
    margin = max(8.0, min(page.width, page.height) * margin_ratio)
    rect = fitz.Rect(
        page.x1 - margin - dest_w,
        page.y1 - margin - dest_h,
        page.x1 - margin,
        page.y1 - margin,
    )
    return clamp_rect_to_page(rect, page)


def remember_stamp_placement(page: fitz.Rect, rect: fitz.Rect) -> StampPlacementMemory:
    page_w = max(float(page.width), 1.0)
    page_h = max(float(page.height), 1.0)
    return StampPlacementMemory(
        width_ratio=min(0.9, max(0.04, float(rect.width) / page_w)),
        right_margin_ratio=max(0.0, float(page.x1 - rect.x1) / page_w),
        bottom_margin_ratio=max(0.0, float(page.y1 - rect.y1) / page_h),
    )


def stamp_rect_from_memory(
    page: fitz.Rect,
    image_width: int,
    image_height: int,
    memory: StampPlacementMemory | None,
) -> fitz.Rect:
    if memory is None:
        return bottom_right_stamp_rect(page, image_width, image_height)
    aspect = _image_aspect(image_width, image_height)
    dest_w = page.width * memory.width_ratio
    dest_h = dest_w / aspect
    max_h = page.height * 0.9
    if dest_h > max_h:
        dest_h = max_h
        dest_w = dest_h * aspect
    dest_w = max(MIN_STAMP_POINTS, dest_w)
    dest_h = dest_w / aspect
    x1 = page.x1 - page.width * memory.right_margin_ratio
    y1 = page.y1 - page.height * memory.bottom_margin_ratio
    return clamp_rect_to_page(fitz.Rect(x1 - dest_w, y1 - dest_h, x1, y1), page)


def stamp_rect_from_drag(
    page: fitz.Rect,
    start: fitz.Point,
    end: fitz.Point,
    image_width: int,
    image_height: int,
) -> fitz.Rect | None:
    raw_w = abs(end.x - start.x)
    raw_h = abs(end.y - start.y)
    if raw_w < 8 and raw_h < 8:
        return None
    aspect = _image_aspect(image_width, image_height)
    if raw_w / max(raw_h, 1e-6) >= aspect:
        width = max(MIN_STAMP_POINTS, raw_w)
        height = width / aspect
    else:
        height = max(MIN_STAMP_POINTS, raw_h)
        width = height * aspect
    x0 = start.x if end.x >= start.x else start.x - width
    y0 = start.y if end.y >= start.y else start.y - height
    return clamp_rect_to_page(fitz.Rect(x0, y0, x0 + width, y0 + height), page)


def resize_stamp_rect(
    rect: fitz.Rect,
    handle: str,
    point: fitz.Point,
    image_width: int,
    image_height: int,
    page: fitz.Rect,
) -> fitz.Rect:
    aspect = _image_aspect(image_width, image_height)
    min_w = MIN_STAMP_POINTS
    min_h = min_w / aspect
    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
    if handle == "se":
        width = max(min_w, point.x - x0)
        height = width / aspect
        next_rect = fitz.Rect(x0, y0, x0 + width, y0 + height)
    elif handle == "nw":
        width = max(min_w, x1 - point.x)
        height = width / aspect
        next_rect = fitz.Rect(x1 - width, y1 - height, x1, y1)
    elif handle == "ne":
        width = max(min_w, point.x - x0)
        height = width / aspect
        next_rect = fitz.Rect(x0, y1 - height, x0 + width, y1)
    elif handle == "sw":
        width = max(min_w, x1 - point.x)
        height = width / aspect
        next_rect = fitz.Rect(x1 - width, y0, x1, y0 + height)
    elif handle == "e":
        width = max(min_w, point.x - x0)
        height = width / aspect
        cy = (y0 + y1) / 2
        next_rect = fitz.Rect(x0, cy - height / 2, x0 + width, cy + height / 2)
    elif handle == "w":
        width = max(min_w, x1 - point.x)
        height = width / aspect
        cy = (y0 + y1) / 2
        next_rect = fitz.Rect(x1 - width, cy - height / 2, x1, cy + height / 2)
    elif handle == "s":
        height = max(min_h, point.y - y0)
        width = height * aspect
        cx = (x0 + x1) / 2
        next_rect = fitz.Rect(cx - width / 2, y0, cx + width / 2, y0 + height)
    elif handle == "n":
        height = max(min_h, y1 - point.y)
        width = height * aspect
        cx = (x0 + x1) / 2
        next_rect = fitz.Rect(cx - width / 2, y1 - height, cx + width / 2, y1)
    else:
        next_rect = fitz.Rect(rect)
    return clamp_rect_to_page(next_rect, page)


def move_stamp_rect(
    origin: fitz.Rect,
    delta: fitz.Point,
    page: fitz.Rect,
) -> fitz.Rect:
    moved = fitz.Rect(
        origin.x0 + delta.x,
        origin.y0 + delta.y,
        origin.x1 + delta.x,
        origin.y1 + delta.y,
    )
    return clamp_rect_to_page(moved, page)


def _image_aspect(image_width: int, image_height: int) -> float:
    width = max(1, int(image_width))
    height = max(1, int(image_height))
    return width / height
