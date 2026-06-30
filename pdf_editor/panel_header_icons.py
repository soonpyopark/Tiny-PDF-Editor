"""Painted icons for side-panel header tool buttons."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_ICON_PX = 18
_ICON_COLOR = QColor("#333333")
_EXCEL_ACCENT = QColor("#217346")


def _blank_pixmap() -> QPixmap:
    pixmap = QPixmap(_ICON_PX, _ICON_PX)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _line_pen(width: float = 1.4) -> QPen:
    return QPen(
        _ICON_COLOR,
        width,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )


def collapse_all_icon() -> QIcon:
    """Stacked lines with an upward chevron (collapse all)."""
    pixmap = _blank_pixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(_line_pen())
    center = _ICON_PX // 2
    painter.drawLine(center, 3, center - 4, 8)
    painter.drawLine(center, 3, center + 4, 8)
    for y in (10, 13, 16):
        painter.drawLine(3, y, 15, y)
    painter.end()
    return QIcon(pixmap)


def expand_all_icon() -> QIcon:
    """Stacked lines with a downward chevron (expand all)."""
    pixmap = _blank_pixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(_line_pen())
    center = _ICON_PX // 2
    for y in (3, 6, 9):
        painter.drawLine(3, y, 15, y)
    painter.drawLine(center, 16, center - 4, 11)
    painter.drawLine(center, 16, center + 4, 11)
    painter.end()
    return QIcon(pixmap)


def excel_export_icon() -> QIcon:
    """Spreadsheet grid with a green accent cell."""
    pixmap = _blank_pixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    outer = 2
    inner = _ICON_PX - outer - 1
    painter.setPen(_line_pen(1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(outer, outer, inner, inner, 2, 2)

    col_x = (outer + 1, outer + inner // 3 + 1, outer + 2 * inner // 3 + 1)
    row_y = (outer + 1, outer + inner // 3 + 1, outer + 2 * inner // 3 + 1)
    right = outer + inner
    bottom = outer + inner
    for x in col_x:
        painter.drawLine(x, outer + 1, x, bottom)
    for y in row_y:
        painter.drawLine(outer + 1, y, right, y)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_EXCEL_ACCENT)
    painter.drawRect(col_x[0], row_y[0], col_x[1] - col_x[0], row_y[1] - row_y[0])
    painter.end()
    return QIcon(pixmap)


HEADER_ICON_SIZE = QSize(16, 16)
