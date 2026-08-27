"""Page-number format, placement, and marker helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass

import fitz

PAGE_NUMBER_ANNOT_TITLE = "tpe:pagenum"

PAGE_NUMBER_POSITIONS = (
    "top_left",
    "top_center",
    "top_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
)

PAGE_NUMBER_STYLE_ARABIC = "arabic"
PAGE_NUMBER_STYLE_ROMAN_LOWER = "roman_lower"
PAGE_NUMBER_STYLE_ROMAN_UPPER = "roman_upper"

PAGE_NUMBER_STYLES = (
    (PAGE_NUMBER_STYLE_ARABIC, "1, 2, 3"),
    (PAGE_NUMBER_STYLE_ROMAN_LOWER, "i, ii, iii"),
    (PAGE_NUMBER_STYLE_ROMAN_UPPER, "I, II, III"),
)

PAGE_NUMBER_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36)
DEFAULT_PAGE_NUMBER_SIZE = 12
DEFAULT_PAGE_NUMBER_RGB = (0.0, 0.0, 0.0)
DEFAULT_PAGE_NUMBER_BACKGROUND_RGB = (1.0, 1.0, 1.0)
DEFAULT_PAGE_NUMBER_POSITION = "bottom_center"
DEFAULT_PAGE_NUMBER_MARGIN_X_MM = 12.0
DEFAULT_PAGE_NUMBER_MARGIN_Y_MM = 10.0
PAGE_NUMBER_MARGIN_MM_MIN = 0.0
PAGE_NUMBER_MARGIN_MM_MAX = 30.0
_MM_TO_PT = 72.0 / 25.4

PAGE_NUMBER_PREFIX_PRESETS = (
    ("(없음, 직접 입력)", ""),
    ("페이지", "페이지 "),
    ("Page", "Page "),
    ("page", "page "),
)
PAGE_NUMBER_SUFFIX_PRESETS = (
    ("(없음, 직접 입력)", ""),
    ("페이지", " 페이지"),
    ("Page", " Page"),
    ("page", " page"),
)

_ROMAN_MAP = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


@dataclass(frozen=True)
class PageNumberOptions:
    position: str = DEFAULT_PAGE_NUMBER_POSITION
    style: str = PAGE_NUMBER_STYLE_ARABIC
    add_hyphens: bool = True
    prefix: str = ""
    suffix: str = ""
    start_page: int = 1
    end_page: int = 0
    start_number: int = 1
    font_size: float = DEFAULT_PAGE_NUMBER_SIZE
    color_rgb: tuple[float, float, float] = DEFAULT_PAGE_NUMBER_RGB
    background_rgb: tuple[float, float, float] = DEFAULT_PAGE_NUMBER_BACKGROUND_RGB
    background_transparent: bool = True
    margin_x_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_X_MM
    margin_y_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_Y_MM

    @property
    def remove_only(self) -> bool:
        return self.position == "none"


def serialize_page_number_options(
    options: PageNumberOptions,
    wipe_rects: list[tuple[float, float, float, float]] | None = None,
) -> str:
    payload = {
        "v": 1,
        "position": options.position,
        "style": options.style,
        "add_hyphens": options.add_hyphens,
        "prefix": options.prefix,
        "suffix": options.suffix,
        "start_page": options.start_page,
        "end_page": options.end_page,
        "start_number": options.start_number,
        "font_size": options.font_size,
        "color_rgb": list(options.color_rgb),
        "background_rgb": list(options.background_rgb),
        "background_transparent": options.background_transparent,
        "margin_x_mm": options.margin_x_mm,
        "margin_y_mm": options.margin_y_mm,
    }
    if wipe_rects:
        payload["wipe_rects"] = [list(rect) for rect in wipe_rects]
    return json.dumps(payload, separators=(",", ":"))


def parse_wipe_rects(content: str) -> list[fitz.Rect]:
    text = (content or "").strip()
    if not text.startswith("{"):
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    raw = data.get("wipe_rects") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    rects: list[fitz.Rect] = []
    for item in raw:
        try:
            rect = fitz.Rect(float(item[0]), float(item[1]), float(item[2]), float(item[3]))
        except (TypeError, ValueError, IndexError):
            continue
        if rect.is_empty or rect.is_infinite:
            continue
        rect.normalize()
        rects.append(rect)
    return rects


def parse_page_number_options(content: str) -> PageNumberOptions | None:
    text = (content or "").strip()
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    position = str(data.get("position") or "")
    if position != "none" and position not in PAGE_NUMBER_POSITIONS:
        return None
    style = str(data.get("style") or PAGE_NUMBER_STYLE_ARABIC)
    if style not in {
        PAGE_NUMBER_STYLE_ARABIC,
        PAGE_NUMBER_STYLE_ROMAN_LOWER,
        PAGE_NUMBER_STYLE_ROMAN_UPPER,
    }:
        style = PAGE_NUMBER_STYLE_ARABIC
    rgb = _parse_rgb(data.get("color_rgb"), DEFAULT_PAGE_NUMBER_RGB)
    if "background_rgb" in data:
        background_rgb = _parse_rgb(data.get("background_rgb"), DEFAULT_PAGE_NUMBER_BACKGROUND_RGB)
    elif data.get("white_background"):
        background_rgb = DEFAULT_PAGE_NUMBER_BACKGROUND_RGB
    else:
        background_rgb = DEFAULT_PAGE_NUMBER_BACKGROUND_RGB
    try:
        font_size = float(data.get("font_size") or DEFAULT_PAGE_NUMBER_SIZE)
    except (TypeError, ValueError):
        font_size = float(DEFAULT_PAGE_NUMBER_SIZE)
    try:
        start_page = int(data.get("start_page") or 1)
        start_number = int(data.get("start_number") or 1)
    except (TypeError, ValueError):
        start_page, start_number = 1, 1
    try:
        end_page = int(data.get("end_page") or 0)
    except (TypeError, ValueError):
        end_page = 0
    return PageNumberOptions(
        position=position,
        style=style,
        add_hyphens=bool(data.get("add_hyphens", True)),
        prefix=str(data.get("prefix") or ""),
        suffix=str(data.get("suffix") or ""),
        start_page=max(1, start_page),
        end_page=max(0, end_page),
        start_number=max(1, start_number),
        font_size=font_size,
        color_rgb=rgb,
        background_rgb=background_rgb,
        background_transparent=bool(data.get("background_transparent", False)),
        margin_x_mm=_parse_margin_mm(data.get("margin_x_mm"), DEFAULT_PAGE_NUMBER_MARGIN_X_MM),
        margin_y_mm=_parse_margin_mm(data.get("margin_y_mm"), DEFAULT_PAGE_NUMBER_MARGIN_Y_MM),
    )


def _parse_margin_mm(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(PAGE_NUMBER_MARGIN_MM_MAX, max(PAGE_NUMBER_MARGIN_MM_MIN, parsed))


def mm_to_pt(mm: float) -> float:
    return float(mm) * _MM_TO_PT


def _parse_rgb(value, default: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, IndexError):
        return default


def infer_page_number_style(text: str) -> tuple[str, bool, int]:
    """Return (style, add_hyphens, displayed_number) from visible page-number text."""
    stripped = (text or "").strip()
    add_hyphens = stripped.startswith("-") and stripped.endswith("-") and len(stripped) >= 3
    body = stripped[1:-1].strip() if add_hyphens else stripped
    if body.isdigit():
        return PAGE_NUMBER_STYLE_ARABIC, add_hyphens, max(1, int(body))
    roman = body.upper()
    if roman and all(ch in "IVXLCDM" for ch in roman):
        value = _from_roman(roman)
        if body.islower():
            return PAGE_NUMBER_STYLE_ROMAN_LOWER, add_hyphens, value
        return PAGE_NUMBER_STYLE_ROMAN_UPPER, add_hyphens, value
    return PAGE_NUMBER_STYLE_ARABIC, add_hyphens, 1


def _from_roman(roman: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(roman):
        value = values.get(char, 0)
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return max(1, total)


def infer_position_from_rect(page, annot_rect: fitz.Rect) -> str:
    visual = fitz.Rect(annot_rect * page.rotation_matrix)
    visual.normalize()
    page_rect = page.rect
    center_x = (visual.x0 + visual.x1) / 2
    center_y = (visual.y0 + visual.y1) / 2
    mid_y = (page_rect.y0 + page_rect.y1) / 2
    vertical = "top" if center_y < mid_y else "bottom"
    width = max(page_rect.width, 1.0)
    rel_x = (center_x - page_rect.x0) / width
    if rel_x < 0.33:
        horizontal = "left"
    elif rel_x > 0.67:
        horizontal = "right"
    else:
        horizontal = "center"
    return f"{vertical}_{horizontal}"


def to_roman(number: int) -> str:
    value = max(1, int(number))
    parts: list[str] = []
    for amount, symbol in _ROMAN_MAP:
        while value >= amount:
            parts.append(symbol)
            value -= amount
    return "".join(parts)


def format_page_number_text(
    number: int,
    style: str,
    add_hyphens: bool,
    prefix: str = "",
    suffix: str = "",
) -> str:
    if style == PAGE_NUMBER_STYLE_ROMAN_LOWER:
        body = to_roman(number).lower()
    elif style == PAGE_NUMBER_STYLE_ROMAN_UPPER:
        body = to_roman(number)
    else:
        body = str(max(0, int(number)))
    core = f"- {body} -" if add_hyphens else body
    return f"{prefix}{core}{suffix}"


def page_number_for_index(page_index: int, options: PageNumberOptions) -> int | None:
    """Return the displayed number for a 0-based page, or None if skipped."""
    page_1based = page_index + 1
    if page_1based < options.start_page:
        return None
    if options.end_page > 0 and page_1based > options.end_page:
        return None
    return options.start_number + (page_1based - options.start_page)


def page_number_origin(
    page_rect: fitz.Rect,
    text_width: float,
    font_size: float,
    position: str,
    margin_x_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_X_MM,
    margin_y_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_Y_MM,
) -> fitz.Point:
    """Return the baseline origin in *displayed* (rotation-aware) page coordinates."""
    margin_x = mm_to_pt(
        _parse_margin_mm(margin_x_mm, DEFAULT_PAGE_NUMBER_MARGIN_X_MM)
    )
    margin_y = mm_to_pt(
        _parse_margin_mm(margin_y_mm, DEFAULT_PAGE_NUMBER_MARGIN_Y_MM)
    )
    max_x = max(0.0, page_rect.width - text_width)
    max_y = max(0.0, page_rect.height - font_size)
    margin_x = min(margin_x, max_x)
    margin_y = min(margin_y, max_y)
    if position.startswith("top"):
        baseline_y = page_rect.y0 + margin_y + font_size * 0.8
    else:
        baseline_y = page_rect.y1 - margin_y
    if position.endswith("left"):
        x = page_rect.x0 + margin_x
    elif position.endswith("right"):
        x = page_rect.x1 - margin_x - text_width
    else:
        x = (page_rect.x0 + page_rect.x1 - text_width) / 2
    return fitz.Point(x, baseline_y)


def page_number_insert_geometry(
    page,
    text_width: float,
    font_size: float,
    position: str,
    margin_x_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_X_MM,
    margin_y_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_Y_MM,
) -> tuple[fitz.Point, fitz.Rect]:
    """Map a displayed position to insert_text / annot coordinates.

    ``page.rect`` follows /Rotate (what the viewer shows), but ``insert_text``
    uses the unrotated mediabox. Convert with ``derotation_matrix``.
    """
    visual_origin = page_number_origin(
        page.rect,
        text_width,
        font_size,
        position,
        margin_x_mm,
        margin_y_mm,
    )
    visual_rect = page_number_text_rect(visual_origin, text_width, font_size)
    insert_origin = fitz.Point(visual_origin) * page.derotation_matrix
    marker = fitz.Rect(visual_rect * page.derotation_matrix)
    marker.normalize()
    return insert_origin, marker


def page_number_background_rect(marker: fitz.Rect, font_size: float) -> fitz.Rect:
    pad_x = max(2.0, font_size * 0.28)
    pad_y = max(1.5, font_size * 0.18)
    rect = fitz.Rect(marker)
    rect.x0 -= pad_x
    rect.x1 += pad_x
    rect.y0 -= pad_y
    rect.y1 += pad_y
    return rect


def page_number_text_rect(origin: fitz.Point, text_width: float, font_size: float) -> fitz.Rect:
    return fitz.Rect(
        origin.x - 1.5,
        origin.y - font_size,
        origin.x + text_width + 1.5,
        origin.y + font_size * 0.35,
    )


def is_page_number_annot(annot) -> bool:
    title = (annot.info or {}).get("title") or ""
    return title == PAGE_NUMBER_ANNOT_TITLE
