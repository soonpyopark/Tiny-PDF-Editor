"""Document highlight list panel (left sidebar, highlights tab)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.panel_header_icons import collapse_all_icon, expand_all_icon
from pdf_editor.side_panel_header import (
    PANEL_HEADER_BTN_HEIGHT,
    SidePanelHeaderBar,
    make_panel_header_icon_button,
)

_EXCEL_EXPORT_BTN_STYLE = """
    QPushButton {
        background-color: #fde8e6;
        border: none;
        border-radius: 3px;
        color: #333333;
        padding: 2px 8px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #fbd0cb;
    }
    QPushButton:pressed {
        background-color: #f5b8b2;
    }
"""


class HighlightPanel(QWidget):
    """Placeholder highlight list; wired for future annotation support."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_bar = SidePanelHeaderBar()
        header = header_bar.row_layout
        header.addWidget(QLabel("  하이라이트"))
        header.addStretch()

        self.btn_collapse = make_panel_header_icon_button(
            collapse_all_icon(),
            "모든 페이지 접기",
        )
        header.addWidget(self.btn_collapse)

        self.btn_expand = make_panel_header_icon_button(
            expand_all_icon(),
            "모든 페이지 펴기",
        )
        header.addWidget(self.btn_expand)

        self.btn_export = QPushButton("엑셀로 저장")
        self.btn_export.setFixedHeight(PANEL_HEADER_BTN_HEIGHT)
        self.btn_export.setToolTip("하이라이트를 Excel로 저장")
        self.btn_export.setStyleSheet(_EXCEL_EXPORT_BTN_STYLE)
        header.addWidget(self.btn_export)

        layout.addWidget(header_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)

        self.empty_hint = QLabel("하이라이트가 없습니다.")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: #666666; font-size: 13px;")
        body_layout.addStretch(1)
        body_layout.addWidget(self.empty_hint)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_document(self, document) -> None:
        self._document = document
        self.refresh()

    def refresh(self) -> None:
        has_pages = bool(self._document and self._document.page_count > 0)
        self.empty_hint.setText(
            "하이라이트가 없습니다." if has_pages else "문서에 페이지가 없습니다."
        )
