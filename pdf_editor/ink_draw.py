"""Freehand drawing (그리기) helpers: stroke clean-up and eraser hit geometry.

Strokes are lists of (x, y) points in *page view* coordinates (points, origin top-left,
page rotation already applied) — the same space the preview image and `get_page_rect` use.
PDF stores ink annotations in unrotated page space, so `document.py` converts at the edge.
"""

from __future__ import annotations

import math

import pymupdf as fitz

# Neo 가 만든 잉크 주석 표식. 지우개는 이 표식이 있는 것만 지운다 (다른 프로그램이 넣은 잉크는 건드리지 않음).
INK_ANNOT_TITLE = "TinyPDF-Ink"

# 한 번에 받는 점 수 상한 (이상한 입력이 엔진을 붙잡지 않게).
MAX_POINTS_PER_STROKE = 20000
MAX_STROKES_PER_CALL = 500

MIN_WIDTH_PT = 0.25
MAX_WIDTH_PT = 200.0

Point = tuple[float, float]


def is_ink_annot(annot) -> bool:
    """True for ink annotations created by this app."""
    try:
        if not annot.type or annot.type[0] != fitz.PDF_ANNOT_INK:
            return False
        return (annot.info or {}).get("title", "") == INK_ANNOT_TITLE
    except (RuntimeError, ValueError, TypeError):
        return False


def clamp_width(width: float) -> float:
    try:
        value = float(width)
    except (TypeError, ValueError):
        value = 2.0
    if not math.isfinite(value):
        value = 2.0
    return min(MAX_WIDTH_PT, max(MIN_WIDTH_PT, value))


def clamp_opacity(opacity: float) -> float:
    try:
        value = float(opacity)
    except (TypeError, ValueError):
        value = 1.0
    if not math.isfinite(value):
        value = 1.0
    return min(1.0, max(0.05, value))


def clean_rgb(raw) -> tuple[float, float, float]:
    """[r, g, b] in 0..1 (or 0..255) -> clamped 0..1 triple. Bad input -> dark gray."""
    try:
        values = [float(v) for v in list(raw)[:3]]
    except (TypeError, ValueError):
        values = []
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        return (0.29, 0.29, 0.29)
    if max(values) > 1.0:
        values = [v / 255.0 for v in values]
    return tuple(min(1.0, max(0.0, v)) for v in values)  # type: ignore[return-value]


def clean_strokes(raw_strokes, bounds: fitz.Rect) -> list[list[Point]]:
    """Validate strokes and clamp their points into *bounds*.

    A single-point stroke becomes a tiny dash so a tap leaves a dot. Strokes without any
    valid point are dropped.
    """
    cleaned: list[list[Point]] = []
    if not isinstance(raw_strokes, (list, tuple)):
        return cleaned
    for raw in list(raw_strokes)[:MAX_STROKES_PER_CALL]:
        if not isinstance(raw, (list, tuple)):
            continue
        points: list[Point] = []
        for item in list(raw)[:MAX_POINTS_PER_STROKE]:
            try:
                x = float(item[0])
                y = float(item[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            x = min(bounds.x1, max(bounds.x0, x))
            y = min(bounds.y1, max(bounds.y0, y))
            if points and points[-1] == (x, y):
                continue
            points.append((x, y))
        if not points:
            continue
        if len(points) == 1:
            x, y = points[0]
            points.append((min(bounds.x1, x + 0.1), y) if x + 0.1 <= bounds.x1 else (x - 0.1, y))
        cleaned.append(points)
    return cleaned


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0) and o1 != 0 and o2 != 0 and o3 != 0 and o4 != 0


def segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    """Shortest distance between segments ab and cd."""
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def polyline_distance(path_a: list[Point], path_b: list[Point]) -> float:
    """Shortest distance between two polylines (single points count as degenerate segments)."""
    if not path_a or not path_b:
        return math.inf
    segs_a = list(zip(path_a, path_a[1:])) or [(path_a[0], path_a[0])]
    segs_b = list(zip(path_b, path_b[1:])) or [(path_b[0], path_b[0])]
    best = math.inf
    for a0, a1 in segs_a:
        for b0, b1 in segs_b:
            dist = segment_distance(a0, a1, b0, b1)
            if dist < best:
                best = dist
                if best <= 0.0:
                    return 0.0
    return best


def bounds_of(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def stroke_hit_by_path(stroke: list[Point], stroke_width: float, path: list[Point], radius: float) -> bool:
    """True if an eraser of *radius* moving along *path* touches a stroke of *stroke_width*."""
    reach = max(0.0, radius) + stroke_width / 2.0
    sx0, sy0, sx1, sy1 = bounds_of(stroke)
    px0, py0, px1, py1 = bounds_of(path)
    # 빠른 탈락: 상자끼리 reach 안에서도 안 겹치면 닿지 않는다.
    if sx1 + reach < px0 or px1 + reach < sx0 or sy1 + reach < py0 or py1 + reach < sy0:
        return False
    return polyline_distance(stroke, path) <= reach


def point_hits_stroke(stroke: list[Point], stroke_width: float, point: Point, slack: float = 3.0) -> bool:
    """True if *point* is within *stroke_width*/2 + *slack* of the polyline."""
    if not stroke:
        return False
    reach = max(0.0, float(stroke_width)) / 2.0 + max(0.0, float(slack))
    sx0, sy0, sx1, sy1 = bounds_of(stroke)
    px, py = point
    if px + reach < sx0 or sx1 + reach < px or py + reach < sy0 or sy1 + reach < py:
        return False
    if len(stroke) == 1:
        return math.hypot(px - stroke[0][0], py - stroke[0][1]) <= reach
    best = math.inf
    for a, b in zip(stroke, stroke[1:]):
        dist = _point_segment_distance(point, a, b)
        if dist < best:
            best = dist
            if best <= reach:
                return True
    return best <= reach
