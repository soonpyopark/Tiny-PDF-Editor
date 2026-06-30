"""Vertical icon tabs to the left of the thumbnail / highlight panels."""

from __future__ import annotations

from enum import IntEnum

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

LEFT_SIDE_NAV_WIDTH = 44
SIDE_PANEL_DIVIDER_COLOR = "#cccccc"
_NAV_ICON_WIDTH = 15
_NAV_ICON_HEIGHT = 18
_NAV_BUTTON_HEIGHT = 40
_NAV_ACTIVE_BG = QColor("#e4e4e4")
_NAV_BORDER = QColor(SIDE_PANEL_DIVIDER_COLOR)
_NAV_ICON = QColor("#333333")


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

        pen = QPen(_NAV_ICON, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._tab == SideNavTab.THUMBNAILS:
            _paint_thumbnail_icon(painter, icon_rect)
        else:
            _paint_highlight_icon(painter, icon_rect)

        painter.end()


def _paint_thumbnail_icon(painter: QPainter, rect) -> None:
    fold = max(4, rect.width() // 5)
    body = rect.adjusted(0, 0, -1, -1)
    painter.drawRect(body)
    fold_left = body.right() - fold + 1
    painter.drawLine(fold_left, body.top(), body.right(), body.top())
    painter.drawLine(fold_left, body.top(), body.right(), body.top() + fold)
    painter.drawLine(fold_left, body.top(), fold_left, body.top() + fold)


def _paint_highlight_icon(painter: QPainter, rect) -> None:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    bubble = rect.adjusted(0, 0, 0, -2)
    radius = max(3, w // 6)
    painter.drawRoundedRect(bubble, radius, radius)
    tail_x = x + w * 0.28
    tail_y = bubble.bottom()
    painter.drawLine(int(tail_x), tail_y, int(tail_x - 2), tail_y + 2)
    painter.drawLine(int(tail_x - 2), tail_y + 2, int(tail_x + 3), tail_y)

    line_pen = QPen(_NAV_ICON, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(line_pen)
    inset = max(3, w // 6)
    inset_x = x + inset
    line_w = w - inset * 2
    line_y1 = y + h * 0.38
    line_y2 = y + h * 0.52
    line_y3 = y + h * 0.66
    painter.drawLine(inset_x, int(line_y1), inset_x + line_w, int(line_y1))
    painter.drawLine(inset_x, int(line_y2), inset_x + int(line_w * 0.72), int(line_y2))
    painter.drawLine(inset_x, int(line_y3), inset_x + int(line_w * 0.85), int(line_y3))


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

        self.btn_thumbnails = _NavTabButton(SideNavTab.THUMBNAILS, "썸네일")
        self.btn_highlights = _NavTabButton(SideNavTab.HIGHLIGHTS, "하이라이트")

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
