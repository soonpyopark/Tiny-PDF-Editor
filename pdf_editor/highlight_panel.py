"""Document highlight / underline list panel (left sidebar)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import PdfDocument, TextMarkupEntry
from pdf_editor.highlight_colors import highlight_qcolor_from_rgb, markup_qcolor_from_rgb
from pdf_editor.markup_export import export_markup_entries_to_csv
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

_PAGE_HEADER_STYLE = """
    QPushButton#pageMarkupHeader {
        background-color: transparent;
        border: none;
        border-bottom: 1px solid #e8e8e8;
        color: #333333;
        font-size: 12px;
        font-weight: 600;
        text-align: left;
        padding: 6px 4px 6px 2px;
    }
    QPushButton#pageMarkupHeader:hover {
        background-color: #f0f0f0;
    }
"""

_ENTRY_BASE_STYLE = """
    QFrame#markupEntryRow {
        border: none;
        border-bottom: 1px solid #eeeeee;
        border-radius: 2px;
    }
    QFrame#markupEntryRow:hover {
        background-color: #f7f7f7;
    }
    QLabel#markupEntryText {
        color: #333333;
        font-size: 12px;
        background: transparent;
    }
"""


class _MarkupEntryRow(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, entry: TextMarkupEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page_index = entry.page_index
        self.setObjectName("markupEntryRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setFrameShape(QFrame.Shape.NoFrame)
        if entry.kind == "highlight":
            fill = highlight_qcolor_from_rgb(entry.rgb)
            accent.setStyleSheet(
                f"background-color: {fill.name(QColor.NameFormat.HexArgb)}; border-radius: 2px;"
            )
        else:
            stroke = markup_qcolor_from_rgb(entry.rgb)
            accent.setStyleSheet(
                f"background-color: {stroke.name()}; border-radius: 2px;"
            )
        layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignTop)

        text = QLabel(entry.text)
        text.setObjectName("markupEntryText")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if entry.kind == "underline":
            stroke = markup_qcolor_from_rgb(entry.rgb)
            text.setStyleSheet(
                f"color: #333333; font-size: 12px; background: transparent;"
                f"border-bottom: 2px solid {stroke.name()}; padding-bottom: 1px;"
            )
        layout.addWidget(text, 1)

        if entry.kind == "highlight":
            fill = highlight_qcolor_from_rgb(entry.rgb)
            self.setStyleSheet(
                _ENTRY_BASE_STYLE
                + f"QFrame#markupEntryRow {{ background-color: {fill.name(QColor.NameFormat.HexArgb)}; }}"
            )
        else:
            self.setStyleSheet(_ENTRY_BASE_STYLE)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._page_index)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _PageMarkupSection(QWidget):
    page_clicked = pyqtSignal(int)

    def __init__(
        self,
        page_index: int,
        entries: list[TextMarkupEntry],
        *,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_index = page_index
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QPushButton(self._header_label(), self)
        self._header.setObjectName("pageMarkupHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet(_PAGE_HEADER_STYLE)
        self._header.clicked.connect(self._on_header_clicked)
        layout.addWidget(self._header)

        self._body = QWidget(self)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        for entry in entries:
            row = _MarkupEntryRow(entry, self._body)
            row.clicked.connect(self.page_clicked.emit)
            body_layout.addWidget(row)
        layout.addWidget(self._body)
        self._body.setVisible(expanded)

    def _header_label(self) -> str:
        chevron = "▼" if self._expanded else "▶"
        return f"  {chevron}  {self._page_index + 1}페이지"

    def _on_header_clicked(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._header.setText(self._header_label())

    def is_expanded(self) -> bool:
        return self._expanded


class HighlightPanel(QWidget):
    page_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PdfDocument | None = None
        self._page_sections: list[_PageMarkupSection] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_bar = SidePanelHeaderBar()
        header = header_bar.row_layout
        header.addWidget(QLabel("  형광펜 & 밑줄"))
        header.addStretch()

        self.btn_collapse = make_panel_header_icon_button(
            collapse_all_icon(),
            "모든 페이지 접기",
        )
        self.btn_collapse.clicked.connect(self._collapse_all_pages)
        header.addWidget(self.btn_collapse)

        self.btn_expand = make_panel_header_icon_button(
            expand_all_icon(),
            "모든 페이지 펴기",
        )
        self.btn_expand.clicked.connect(self._expand_all_pages)
        header.addWidget(self.btn_expand)

        self.btn_export = QPushButton("엑셀로 저장")
        self.btn_export.setFixedHeight(PANEL_HEADER_BTN_HEIGHT)
        self.btn_export.setToolTip("형광펜·밑줄을 Excel로 저장")
        self.btn_export.setStyleSheet(_EXCEL_EXPORT_BTN_STYLE)
        self.btn_export.clicked.connect(self._export_to_excel)
        header.addWidget(self.btn_export)

        layout.addWidget(header_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 4, 4, 4)
        self._body_layout.setSpacing(4)

        self._empty_hint = QLabel("형광펜이나 밑줄 친 내용이 없습니다.")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color: #666666; font-size: 13px;")
        self._body_layout.addStretch(1)
        self._body_layout.addWidget(self._empty_hint)
        self._body_layout.addStretch(1)

        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, 1)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_document(self, document: PdfDocument | None) -> None:
        self._document = document
        self.refresh()

    def _resolve_document(self) -> PdfDocument | None:
        widget: QWidget | None = self
        while widget is not None:
            doc = getattr(widget, "document", None)
            if isinstance(doc, PdfDocument):
                return doc
            widget = widget.parentWidget()
        return self._document

    def refresh(self) -> None:
        self._document = self._resolve_document()
        self._clear_body()
        if not self._document or self._document.page_count == 0:
            self._show_empty_hint("문서에 페이지가 없습니다.")
            return

        entries = self._document.get_text_markup_entries()
        if not entries:
            self._show_empty_hint("형광펜이나 밑줄 친 내용이 없습니다.")
            return

        grouped: dict[int, list[TextMarkupEntry]] = defaultdict(list)
        for entry in entries:
            grouped[entry.page_index].append(entry)

        self._page_sections.clear()
        for page_index in sorted(grouped):
            section = _PageMarkupSection(page_index, grouped[page_index], expanded=True, parent=self._body)
            section.page_clicked.connect(self.page_selected.emit)
            self._body_layout.addWidget(section)
            self._page_sections.append(section)

        self._body_layout.addStretch(1)

    def _clear_body(self) -> None:
        self._page_sections.clear()
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is self._empty_hint:
                widget.hide()
                continue
            if widget is not None:
                widget.deleteLater()

    def _show_empty_hint(self, message: str) -> None:
        self._empty_hint.setText(message)
        self._empty_hint.show()
        self._body_layout.addStretch(1)
        self._body_layout.addWidget(self._empty_hint)
        self._body_layout.addStretch(1)

    def _collapse_all_pages(self) -> None:
        for section in self._page_sections:
            section.set_expanded(False)

    def _expand_all_pages(self) -> None:
        for section in self._page_sections:
            section.set_expanded(True)

    def _export_to_excel(self) -> None:
        if not self._document or self._document.page_count == 0:
            QMessageBox.information(self, "엑셀로 저장", "저장할 문서가 없습니다.")
            return

        entries = self._document.get_text_markup_entries()
        if not entries:
            QMessageBox.information(self, "엑셀로 저장", "저장할 형광펜·밑줄이 없습니다.")
            return

        default_name = "형광펜_밑줄.csv"
        if self._document.source_path:
            default_name = f"{Path(self._document.source_path).stem}_형광펜_밑줄.csv"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "엑셀로 저장",
            default_name,
            "Excel CSV (*.csv);;모든 파일 (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path = f"{path}.csv"

        try:
            export_markup_entries_to_csv(entries, path)
        except OSError as exc:
            QMessageBox.critical(self, "엑셀로 저장", f"파일을 저장하지 못했습니다.\n{exc}")
            return

        QMessageBox.information(self, "엑셀로 저장", "저장했습니다.")
