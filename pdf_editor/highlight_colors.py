"""Preset colors and circle icons for text highlights."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

DEFAULT_HIGHLIGHT_COLOR_ID = "yellow"

_preferred_color_id: str = DEFAULT_HIGHLIGHT_COLOR_ID
_preferred_custom_rgb: tuple[float, float, float] | None = None

HIGHLIGHT_PRESETS: dict[str, str] = {
    "gray": "#e0e0e0",
    "yellow": "#fff59d",
    "red": "#ffcdd2",
    "blue": "#bbdefb",
    "green": "#c8e6c9",
}

HIGHLIGHT_PRESET_ORDER = ("gray", "yellow", "red", "blue", "green")

HIGHLIGHT_RGB: dict[str, tuple[float, float, float]] = {
    key: (
        QColor(hex_color).redF(),
        QColor(hex_color).greenF(),
        QColor(hex_color).blueF(),
    )
    for key, hex_color in HIGHLIGHT_PRESETS.items()
}

UNDERLINE_PRESETS: dict[str, str] = {
    "gray": "#616161",
    "yellow": "#f9a825",
    "red": "#e53935",
    "blue": "#1e88e5",
    "green": "#43a047",
}

UNDERLINE_PRESET_ORDER = ("gray", "yellow", "red", "blue", "green")

UNDERLINE_RGB: dict[str, tuple[float, float, float]] = {
    key: (
        QColor(hex_color).redF(),
        QColor(hex_color).greenF(),
        QColor(hex_color).blueF(),
    )
    for key, hex_color in UNDERLINE_PRESETS.items()
}

HIGHLIGHT_OVERLAY_ALPHA = 115

_RGB_MATCH_TOLERANCE = 0.02


def preferred_highlight_rgb() -> tuple[float, float, float]:
    if _preferred_custom_rgb is not None:
        return _preferred_custom_rgb
    return HIGHLIGHT_RGB.get(_preferred_color_id, HIGHLIGHT_RGB[DEFAULT_HIGHLIGHT_COLOR_ID])


def preferred_highlight_icon(*, size: int = 14) -> QIcon:
    if _preferred_custom_rgb is not None:
        color = QColor.fromRgbF(*_preferred_custom_rgb)
        return color_circle_icon_from_qcolor(color, size=size)
    return color_circle_icon(_preferred_color_id, size=size)


def set_preferred_highlight_color_id(color_id: str) -> None:
    global _preferred_color_id, _preferred_custom_rgb
    if color_id not in HIGHLIGHT_PRESETS:
        color_id = DEFAULT_HIGHLIGHT_COLOR_ID
    _preferred_color_id = color_id
    _preferred_custom_rgb = None


def set_preferred_highlight_rgb(rgb: tuple[float, float, float]) -> None:
    global _preferred_color_id, _preferred_custom_rgb
    for color_id, preset_rgb in HIGHLIGHT_RGB.items():
        if _rgb_near(rgb, preset_rgb):
            _preferred_color_id = color_id
            _preferred_custom_rgb = None
            return
    _preferred_custom_rgb = rgb


DEFAULT_UNDERLINE_COLOR_ID = "red"

_preferred_underline_color_id: str = DEFAULT_UNDERLINE_COLOR_ID
_preferred_underline_custom_rgb: tuple[float, float, float] | None = None


def preferred_underline_rgb() -> tuple[float, float, float]:
    if _preferred_underline_custom_rgb is not None:
        return _preferred_underline_custom_rgb
    return UNDERLINE_RGB.get(
        _preferred_underline_color_id,
        UNDERLINE_RGB[DEFAULT_UNDERLINE_COLOR_ID],
    )


def preferred_underline_icon(*, size: int = 14) -> QIcon:
    if _preferred_underline_custom_rgb is not None:
        color = QColor.fromRgbF(*_preferred_underline_custom_rgb)
        return color_circle_icon_from_qcolor(color, size=size)
    return underline_color_circle_icon(_preferred_underline_color_id, size=size)


def set_preferred_underline_color_id(color_id: str) -> None:
    global _preferred_underline_color_id, _preferred_underline_custom_rgb
    if color_id not in UNDERLINE_PRESETS:
        color_id = DEFAULT_UNDERLINE_COLOR_ID
    _preferred_underline_color_id = color_id
    _preferred_underline_custom_rgb = None


def set_preferred_underline_rgb(rgb: tuple[float, float, float]) -> None:
    global _preferred_underline_color_id, _preferred_underline_custom_rgb
    for color_id, preset_rgb in UNDERLINE_RGB.items():
        if _rgb_near(rgb, preset_rgb):
            _preferred_underline_color_id = color_id
            _preferred_underline_custom_rgb = None
            return
    _preferred_underline_custom_rgb = rgb


def markup_qcolor_from_rgb(rgb: tuple[float, float, float]) -> QColor:
    return QColor.fromRgbF(rgb[0], rgb[1], rgb[2])


def _rgb_near(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> bool:
    return all(abs(left[i] - right[i]) < _RGB_MATCH_TOLERANCE for i in range(3))


def highlight_qcolor(color_id: str) -> QColor:
    hex_color = HIGHLIGHT_PRESETS.get(color_id, HIGHLIGHT_PRESETS[DEFAULT_HIGHLIGHT_COLOR_ID])
    color = QColor(hex_color)
    color.setAlpha(HIGHLIGHT_OVERLAY_ALPHA)
    return color


def highlight_qcolor_from_rgb(rgb: tuple[float, float, float]) -> QColor:
    color = QColor.fromRgbF(rgb[0], rgb[1], rgb[2])
    color.setAlpha(HIGHLIGHT_OVERLAY_ALPHA)
    return color


def color_circle_icon(color_id: str, *, size: int = 14) -> QIcon:
    hex_color = HIGHLIGHT_PRESETS.get(color_id, HIGHLIGHT_PRESETS[DEFAULT_HIGHLIGHT_COLOR_ID])
    return _circle_icon(QColor(hex_color), size=size)


def underline_color_circle_icon(color_id: str, *, size: int = 14) -> QIcon:
    hex_color = UNDERLINE_PRESETS.get(color_id, UNDERLINE_PRESETS[DEFAULT_UNDERLINE_COLOR_ID])
    return _circle_icon(QColor(hex_color), size=size)


def color_circle_icon_from_qcolor(color: QColor, *, size: int = 14) -> QIcon:
    return _circle_icon(color, size=size)


def _circle_icon(color: QColor, *, size: int = 14) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#aaaaaa"), 1))
    painter.setBrush(color)
    margin = 1
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    painter.end()
    return QIcon(pixmap)


def rgb_tuple_to_hex(rgb: tuple[float, float, float]) -> str:
    color = QColor.fromRgbF(rgb[0], rgb[1], rgb[2])
    return color.name(QColor.NameFormat.HexRgb)
