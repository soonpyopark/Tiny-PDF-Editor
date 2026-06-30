"""Document highlight / underline list panel (left sidebar)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QTextOption
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import PdfDocument, TextMarkupEntry
from pdf_editor.highlight_colors import highlight_qcolor_from_rgb, markup_qcolor_from_rgb
from pdf_editor.markup_export import export_markup_entries_to_xlsx
from pdf_editor.panel_header_icons import collapse_all_icon, expand_all_icon
from pdf_editor.side_panel_header import (
    PANEL_HEADER_BTN_HEIGHT,
    SidePanelHeaderBar,
    make_panel_divider,
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

_PANEL_SURFACE_STYLE = """
    HighlightPanel {
        background-color: #ffffff;
    }
    QScrollArea#markupPanelScroll {
        background-color: #ffffff;
        border: none;
    }
    QWidget#markupPanelBody {
        background-color: #ffffff;
    }
"""

_PAGE_HEADER_STYLE = """
    QPushButton#pageMarkupHeader {
        background-color: #efefef;
        border: none;
        border-bottom: 1px solid #e8e8e8;
        color: #333333;
        font-size: 12px;
        font-weight: 600;
        text-align: left;
        padding: 6px 4px 6px 2px;
    }
    QPushButton#pageMarkupHeader:hover {
        background-color: #e5e5e5;
    }
"""

_ENTRY_SELECTED_BORDER = "border: 1px solid #666666;"

_ENTRY_ROW_SPACING = 6
_ENTRY_SECTION_INSET = 4

_ENTRY_BASE_STYLE = """
    QFrame#markupEntryRow {
        border: none;
        border-radius: 3px;
    }
    QFrame#markupEntryRow:hover {
        background-color: #f7f7f7;
    }
    QLabel#markupEntryText {
        color: #333333;
        font-size: 12px;
        background: transparent;
    }
    QTextEdit#markupEntryText {
        color: #333333;
        font-size: 12px;
        background: transparent;
        border: none;
    }
"""


class _MarkupEntryText(QTextEdit):
    """Read-only entry text that wraps at word boundaries or by character/syllable."""

    def __init__(
        self,
        text: str,
        *,
        underline_color: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("markupEntryText")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setViewportMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)
        wrap_option = QTextOption()
        wrap_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(wrap_option)
        style = (
            "QTextEdit#markupEntryText {"
            " color: #333333;"
            " font-size: 12px;"
            " background: transparent;"
            " border: none;"
        )
        if underline_color is not None:
            style += (
                f" border-bottom: 2px solid {underline_color};"
                " padding-bottom: 1px;"
            )
        style += " }"
        self.setStyleSheet(style)
        self.setPlainText(text)
        self._sync_height()

    def _sync_height(self) -> None:
        width = max(1, self.viewport().width())
        self.document().setTextWidth(width)
        height = int(self.document().size().height()) + 2
        self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_height()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_height()


class _MarkupEntryRow(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, entry: TextMarkupEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entry = entry
        self._selected = False
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

        underline_color = None
        if entry.kind == "underline":
            underline_color = markup_qcolor_from_rgb(entry.rgb).name()
        text = _MarkupEntryText(entry.text, underline_color=underline_color)
        self._entry_text = text
        layout.addWidget(text, 1)

        self._apply_style()

    def sync_text_layout(self) -> None:
        self._entry_text._sync_height()

    def entry(self) -> TextMarkupEntry:
        return self._entry

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def is_selected(self) -> bool:
        return self._selected

    def _apply_style(self) -> None:
        border = _ENTRY_SELECTED_BORDER if self._selected else "border: none;"
        if self._entry.kind == "highlight":
            fill = highlight_qcolor_from_rgb(self._entry.rgb)
            self.setStyleSheet(
                _ENTRY_BASE_STYLE
                + "QFrame#markupEntryRow {"
                f" background-color: {fill.name(QColor.NameFormat.HexArgb)};"
                f" {border}"
                " }"
            )
        else:
            self.setStyleSheet(
                _ENTRY_BASE_STYLE
                + "QFrame#markupEntryRow {"
                f" {border}"
                " }"
            )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _PageMarkupSection(QWidget):
    entry_clicked = pyqtSignal(object)

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
        body_layout.setContentsMargins(
            _ENTRY_SECTION_INSET,
            4,
            _ENTRY_SECTION_INSET,
            4,
        )
        body_layout.setSpacing(_ENTRY_ROW_SPACING)
        self._rows: list[_MarkupEntryRow] = []
        for entry in entries:
            row = _MarkupEntryRow(entry, self._body)
            row.clicked.connect(self.entry_clicked.emit)
            body_layout.addWidget(row)
            self._rows.append(row)
        layout.addWidget(self._body)
        self._body.setVisible(expanded)

    def page_index(self) -> int:
        return self._page_index

    def rows(self) -> list[_MarkupEntryRow]:
        return self._rows

    def row_for_entry(self, entry: TextMarkupEntry) -> _MarkupEntryRow | None:
        for row in self._rows:
            if PdfDocument._text_markup_entries_match(row.entry(), entry):
                return row
        return None

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
    entry_selected = pyqtSignal(object)
    markup_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PdfDocument | None = None
        self._page_sections: list[_PageMarkupSection] = []
        self._selected_row: _MarkupEntryRow | None = None
        self._selected_entry: TextMarkupEntry | None = None

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_PANEL_SURFACE_STYLE)

        layout.addWidget(make_panel_divider())

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
        self._scroll.setObjectName("markupPanelScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._body = QWidget()
        self._body.setObjectName("markupPanelBody")
        self._body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 4, 4, 4)
        self._body_layout.setSpacing(8)

        self._empty_hint = QLabel("형광펜이나 밑줄 친 내용이 없습니다.")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color: #666666; font-size: 13px;")
        self._body_layout.addStretch(1)
        self._body_layout.addWidget(self._empty_hint)
        self._body_layout.addStretch(1)

        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(make_panel_divider())

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _sync_entry_text_heights(self) -> None:
        for section in self._page_sections:
            for row in section.rows():
                row.sync_text_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_entry_text_heights()

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
        preserved_entry = self._selected_entry
        self._selected_row = None
        self._selected_entry = None
        for page_index in sorted(grouped):
            section = _PageMarkupSection(page_index, grouped[page_index], expanded=True, parent=self._body)
            section.entry_clicked.connect(self._on_entry_clicked)
            self._body_layout.addWidget(section)
            self._page_sections.append(section)

        self._body_layout.addStretch(1)
        if preserved_entry is not None:
            self.select_entry(preserved_entry, scroll=False)
        QTimer.singleShot(0, self._sync_entry_text_heights)

    def _clear_body(self) -> None:
        self._page_sections.clear()
        self._selected_row = None
        self._selected_entry = None
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

        default_name = "형광펜_밑줄.xlsx"
        if self._document.source_path:
            default_name = f"{Path(self._document.source_path).stem}_형광펜_밑줄.xlsx"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "엑셀로 저장",
            default_name,
            "Excel 통합 문서 (*.xlsx);;모든 파일 (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path = f"{path}.xlsx"

        try:
            export_markup_entries_to_xlsx(entries, path)
        except OSError as exc:
            QMessageBox.critical(self, "엑셀로 저장", f"파일을 저장하지 못했습니다.\n{exc}")
            return

        QMessageBox.information(self, "엑셀로 저장", "저장했습니다.")

    def scroll_to_current_context(self, page_index: int) -> None:
        """Scroll the list to the selected entry, or to *page_index* if none."""
        if self._selected_entry is not None:
            self.select_entry(self._selected_entry, scroll=True)
            return
        self.scroll_to_page(page_index)

    def scroll_to_page(self, page_index: int) -> None:
        for section in self._page_sections:
            if section.page_index() == page_index:
                section.set_expanded(True)
                self._scroll.ensureWidgetVisible(section, 0, 24)
                return

    def _on_entry_clicked(self, row: _MarkupEntryRow) -> None:
        self._select_row(row, scroll=False)
        self.entry_selected.emit(row.entry())
        self.setFocus()

    def select_entry(self, entry: TextMarkupEntry, *, scroll: bool = True) -> bool:
        if not self._page_sections and self._document:
            entries = self._document.get_text_markup_entries()
            if entries:
                self.refresh()
        row = self._find_row_for_entry(entry)
        if row is None:
            return False
        self._select_row(row, scroll=scroll)
        return True

    def _find_row_for_entry(self, entry: TextMarkupEntry) -> _MarkupEntryRow | None:
        for section in self._page_sections:
            row = section.row_for_entry(entry)
            if row is not None:
                return row
        return None

    def _select_row(self, row: _MarkupEntryRow | None, *, scroll: bool = True) -> None:
        if self._selected_row is not None:
            self._selected_row.set_selected(False)
        self._selected_row = row
        self._selected_entry = row.entry() if row is not None else None
        if row is None:
            return
        row.set_selected(True)
        if not scroll:
            return
        section = row.parentWidget()
        while section is not None and not isinstance(section, _PageMarkupSection):
            section = section.parentWidget()
        if isinstance(section, _PageMarkupSection):
            section.set_expanded(True)
        self._scroll.ensureWidgetVisible(row, 24, 24)

    def has_selected_entry(self) -> bool:
        return self._selected_entry is not None

    def try_remove_selected(self) -> bool:
        if self._selected_entry is None:
            return False
        document = self._resolve_document()
        if document is None:
            return False
        if not document.remove_text_markup_entry(self._selected_entry):
            return False
        self._selected_row = None
        self._selected_entry = None
        self.markup_changed.emit()
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.try_remove_selected():
                event.accept()
                return
        super().keyPressEvent(event)
