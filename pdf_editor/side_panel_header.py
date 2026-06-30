"""Shared header row + divider for thumbnail / highlight side panels."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.left_side_nav import SIDE_PANEL_DIVIDER_COLOR
from pdf_editor.panel_header_icons import HEADER_ICON_SIZE

PANEL_HEADER_BTN_HEIGHT = 26
PANEL_HEADER_BTN_WIDTH = 28
PANEL_HEADER_ROW_HEIGHT = PANEL_HEADER_BTN_HEIGHT + 8
PANEL_HEADER_BAR_HEIGHT = PANEL_HEADER_ROW_HEIGHT + 1


def make_panel_header_icon_button(
    icon: QIcon,
    tooltip: str,
    *,
    parent: QWidget | None = None,
) -> QPushButton:
    button = QPushButton(parent)
    button.setIcon(icon)
    button.setIconSize(HEADER_ICON_SIZE)
    button.setFixedSize(PANEL_HEADER_BTN_WIDTH, PANEL_HEADER_BTN_HEIGHT)
    button.setToolTip(tooltip)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


class SidePanelHeaderBar(QWidget):
    """Fixed-height title row with a #cccccc divider beneath."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(PANEL_HEADER_BAR_HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._row = QWidget()
        self._row.setFixedHeight(PANEL_HEADER_ROW_HEIGHT)
        self.row_layout = QHBoxLayout(self._row)
        self.row_layout.setContentsMargins(4, 4, 4, 4)
        self.row_layout.setSpacing(4)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.NoFrame)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {SIDE_PANEL_DIVIDER_COLOR};")

        outer.addWidget(self._row)
        outer.addWidget(divider)
