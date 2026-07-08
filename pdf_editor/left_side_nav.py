"""Vertical icon tabs to the left of the thumbnail / highlight panels."""

from __future__ import annotations

from enum import IntEnum

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

LEFT_SIDE_NAV_WIDTH = 44
SIDE_PANEL_DIVIDER_COLOR = "#cccccc"
_NAV_ICON_WIDTH = 18
_NAV_ICON_HEIGHT = 18
_NAV_BUTTON_HEIGHT = 40
_NAV_ACTIVE_BG = QColor("#e4e4e4")
_NAV_BORDER = QColor(SIDE_PANEL_DIVIDER_COLOR)
_NAV_ICON = QColor("#333333")
_NAV_HIGHLIGHT_ACCENT = QColor("#ffd54a")


class SideNavTab(IntEnum):
    THUMBNAILS = 0
    HIGHLIGHTS = 1


class _NavTabButton(QPushButton):
    def __init__(self, tab: SideNavTab, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tab = tab
        self.setCheckable(True)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(LEFT_SIDE_NAV_WIDTH, _NAV_BUTTON_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isChecked():
            inset = 6
            bg_rect = self.rect().adjusted(inset, 6, -inset, -6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_NAV_ACTIVE_BG)
            painter.drawRoundedRect(bg_rect, 6, 6)

        icon_rect = self.rect()
        icon_rect.setSize(QSize(_NAV_ICON_WIDTH, _NAV_ICON_HEIGHT))
        icon_rect.moveCenter(self.rect().center())
        rectf = QRectF(icon_rect)

        if self._tab == SideNavTab.THUMBNAILS:
            _paint_thumbnail_icon(painter, rectf)
        else:
            _paint_highlight_icon(painter, rectf)

        painter.end()


def _paint_thumbnail_icon(painter: QPainter, rect: QRectF) -> None:
    """Outline gallery: a large frame with a small image mark inside."""
    stroke = QPen(_NAV_ICON, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(stroke)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    frame = rect.adjusted(0.75, 0.75, -0.75, -0.75)
    radius = rect.width() * 0.16
    painter.drawRoundedRect(frame, radius, radius)

    w, h = frame.width(), frame.height()
    dot_r = w * 0.1
    painter.drawEllipse(
        QPointF(frame.left() + w * 0.34, frame.top() + h * 0.32),
        dot_r,
        dot_r,
    )

    base_y = frame.bottom() - 1.0
    ridge = QPolygonF(
        [
            QPointF(frame.left() + w * 0.08, base_y),
            QPointF(frame.left() + w * 0.4, frame.top() + h * 0.5),
            QPointF(frame.left() + w * 0.58, frame.top() + h * 0.68),
            QPointF(frame.left() + w * 0.78, frame.top() + h * 0.42),
            QPointF(frame.right() - w * 0.06, base_y),
        ]
    )
    painter.drawPolyline(ridge)


def _paint_highlight_icon(painter: QPainter, rect: QRectF) -> None:
    """Outline highlighter marker drawn diagonally, with a colored underline."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()

    stroke = QPen(_NAV_ICON, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    painter.save()
    painter.translate(rect.center().x(), rect.center().y() - h * 0.08)
    painter.rotate(45)
    pen_w = w * 0.5
    pen_h = h * 0.88
    barrel_h = pen_h * 0.46
    barrel = QRectF(-pen_w / 2, -pen_h / 2, pen_w, barrel_h)
    collar_top = barrel.bottom()
    collar_h = pen_h * 0.12
    nib_bottom = pen_h / 2

    painter.setPen(stroke)
    painter.drawRoundedRect(barrel, pen_w * 0.28, pen_w * 0.28)

    nib = QPolygonF(
        [
            QPointF(-pen_w / 2, collar_top),
            QPointF(pen_w / 2, collar_top),
            QPointF(pen_w / 2, collar_top + collar_h),
            QPointF(pen_w * 0.26, nib_bottom),
            QPointF(-pen_w * 0.26, nib_bottom),
            QPointF(-pen_w / 2, collar_top + collar_h),
        ]
    )
    painter.drawPolygon(nib)
    painter.restore()

    accent_pen = QPen(_NAV_HIGHLIGHT_ACCENT, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(accent_pen)
    underline_y = y + h - 0.5
    painter.drawLine(QPointF(x + w * 0.1, underline_y), QPointF(x + w * 0.9, underline_y))


class LeftSideNavBar(QWidget):
    """Narrow vertical tab strip: thumbnails (top), highlights (bottom)."""

    tab_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(LEFT_SIDE_NAV_WIDTH)
        self.setObjectName("leftSideNavBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#leftSideNavBar {"
            " background-color: #f5f5f5;"
            f" border-right: 1px solid {_NAV_BORDER.name()};"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self.btn_thumbnails = _NavTabButton(
            SideNavTab.THUMBNAILS, "썸네일\n두번 클릭하면 메뉴가 사라집니다."
        )
        self.btn_highlights = _NavTabButton(
            SideNavTab.HIGHLIGHTS, "형광펜 & 밑줄\n두번 클릭하면 메뉴가 사라집니다."
        )

        for index, button in enumerate((self.btn_thumbnails, self.btn_highlights)):
            self._group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)

        self.btn_thumbnails.setChecked(True)
        self._group.idClicked.connect(self.tab_changed.emit)

    def current_tab(self) -> SideNavTab:
        return SideNavTab(self._group.checkedId())

    def set_current_tab(self, tab: SideNavTab) -> None:
        button = self._group.button(int(tab))
        if button is not None:
            button.setChecked(True)
