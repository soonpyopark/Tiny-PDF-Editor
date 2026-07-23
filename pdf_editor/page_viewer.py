"""Main page viewer with zoom and navigation controls."""

from __future__ import annotations

import fitz
from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QIcon, QKeyEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.cross_page_selection import CrossPageSelection, PageSelectionSegment
from pdf_editor.document import PdfDocument, TextMarkupEntry
from pdf_editor.highlight_colors import (
    DEFAULT_HIGHLIGHT_COLOR_ID,
    DEFAULT_UNDERLINE_COLOR_ID,
    HIGHLIGHT_RGB,
    UNDERLINE_RGB,
    highlight_qcolor_from_rgb,
    markup_qcolor_from_rgb,
    preferred_highlight_rgb,
    preferred_underline_rgb,
    set_preferred_highlight_color_id,
    set_preferred_highlight_rgb,
    set_preferred_underline_color_id,
    set_preferred_underline_rgb,
)
from pdf_editor.pixmap_utils import pixmap_from_fitz
from pdf_editor.text_highlight_menu import build_text_selection_context_menu

ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 500, 600]
MAX_ZOOM_PERCENT = 600
MAX_ZOOM = MAX_ZOOM_PERCENT / 100.0
ZOOM_STEP_FACTOR = 1.1
ARROW_SCROLL_STEP = 90
WHEEL_SCROLL_MULTIPLIER = 1.5
SMOOTH_SCROLL_DURATION_MS = 260
PREVIEW_BACKGROUND = "#efefef"
SPREAD_GAP_PX = 12
PREVIEW_SCROLLBAR_STYLE = """
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.28);
    min-height: 36px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 0, 0, 0.45);
}
QScrollBar::handle:vertical:pressed {
    background: rgba(0, 0, 0, 0.55);
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0px 2px 2px 2px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 0, 0, 0.28);
    min-width: 36px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(0, 0, 0, 0.45);
}
QScrollBar::handle:horizontal:pressed {
    background: rgba(0, 0, 0, 0.55);
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    height: 0px;
    background: transparent;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
"""
EMPTY_PREVIEW_HINT = (
    "병합할 이미지나 PDF 를 좌측 썸네일 화면으로\n"
    "드래그 앤 드랍으로 추가해주세요"
)
_LOG_HEADER_HEIGHT = 28
_LOG_BODY_MIN_HEIGHT = 96
_LOG_BODY_MAX_HEIGHT = 160
_LOG_HEADER_STYLE = (
    "QWidget#logHeader {"
    "background-color: #2d2d2d;"
    "border-top: 1px solid #333333;"
    "}"
)
_LOG_TAB_STYLE = """
    QPushButton {
        color: #cccccc;
        background: transparent;
        border: none;
        border-radius: 4px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 600;
        text-align: left;
    }
    QPushButton:hover {
        background-color: #3a3a3a;
        color: #ffffff;
    }
"""
_LOG_CLOSE_STYLE = """
    QPushButton {
        color: #aaaaaa;
        background: transparent;
        border: none;
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 14px;
        font-weight: 600;
        min-width: 24px;
        max-width: 24px;
    }
    QPushButton:hover {
        background-color: #5a2020;
        color: #ffcccc;
    }
"""


def _edge_nav_icon(to_first: bool) -> QIcon:
    """Draw |< or >| icons that stay readable at small button sizes."""
    width, height = 20, 14
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(Qt.GlobalColor.black)
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    mid_y = height // 2
    if to_first:
        painter.drawLine(2, 2, 2, height - 2)
        painter.drawLine(16, 2, 7, mid_y)
        painter.drawLine(7, mid_y, 16, height - 2)
    else:
        painter.drawLine(4, 2, 13, mid_y)
        painter.drawLine(13, mid_y, 4, height - 2)
        painter.drawLine(width - 2, 2, width - 2, height - 2)

    painter.end()
    return QIcon(pixmap)


def _arrow_nav_icon(to_left: bool) -> QIcon:
    """Draw < or > chevron icons for previous/next page buttons."""
    width, height = 14, 14
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(Qt.GlobalColor.black)
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    mid_y = height // 2
    if to_left:
        painter.drawLine(width - 2, 2, 3, mid_y)
        painter.drawLine(3, mid_y, width - 2, height - 2)
    else:
        painter.drawLine(2, 2, width - 3, mid_y)
        painter.drawLine(width - 3, mid_y, 2, height - 2)

    painter.end()
    return QIcon(pixmap)


class _InlineTextEditor(QLineEdit):
    """Single-line editor overlaid on a text line for in-place overwrite."""

    commit_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PageCanvas(QLabel):
    """Rendered page with drag-to-select text overlay."""

    text_highlight_added = pyqtSignal()
    text_edited = pyqtSignal()
    markup_clicked = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._document: PdfDocument | None = None
        self._page_index = 0
        self._zoom = 1.0
        self._anchor: QPoint | None = None
        self._cursor: QPoint | None = None
        self._selection_highlights: list[QRect] = []
        self._selection_page_rect: fitz.Rect | None = None
        self._selected_text = ""
        self._selected_words: list = []
        self._text_highlights: list[tuple[QRect, QColor]] = []
        self._text_underlines: list[tuple[tuple[float, float, float, float], QColor]] = []
        self._search_highlights: list[QRect] = []
        self._active_search_highlight = -1
        self._viewer: PageViewer | None = None
        self._stored_segment_highlights: list[QRect] = []

    def set_page_viewer(self, viewer: PageViewer) -> None:
        self._viewer = viewer

    def set_content(
        self,
        pixmap: QPixmap,
        document: PdfDocument | None,
        page_index: int,
        zoom: float,
        *,
        clear_selection: bool = True,
    ) -> None:
        self._document = document
        self._page_index = page_index
        self._zoom = zoom
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        if clear_selection:
            self.clear_selection(clear_cross_page=False)
        else:
            self._anchor = None
            self._cursor = None
            self._selection_highlights = []
            self._selection_page_rect = None
            self._selected_text = ""
            self._selected_words = []
        self._rebuild_stored_segment_highlights()

    def clear_selection(self, *, clear_cross_page: bool = True) -> None:
        if self.mouseGrabber() == self:
            self.releaseMouse()
        self._anchor = None
        self._cursor = None
        self._selection_highlights = []
        self._selection_page_rect = None
        self._selected_text = ""
        self._selected_words = []
        self._stored_segment_highlights = []
        if clear_cross_page and self._viewer is not None:
            self._viewer.clear_cross_page_selection()
        self.update()

    def set_text_highlights(self, highlights: list[tuple[QRect, QColor]]) -> None:
        self._text_highlights = highlights
        self.update()

    def set_text_underlines(
        self,
        underlines: list[tuple[tuple[float, float, float, float], QColor]],
    ) -> None:
        self._text_underlines = underlines
        self.update()

    def clear_search_highlights(self) -> None:
        self._search_highlights = []
        self._active_search_highlight = -1
        self.update()

    def set_search_highlights(
        self,
        highlights: list[QRect],
        active_index: int = -1,
    ) -> None:
        self._search_highlights = highlights
        self._active_search_highlight = active_index
        self.update()

    def selected_text(self) -> str:
        return self._effective_selected_text()

    def _effective_selected_text(self) -> str:
        if self._viewer is not None and self._viewer._cross_page_selection is not None:
            cross = self._viewer._cross_page_selection
            parts = [
                cross.segments[index].text
                for index in sorted(cross.segments)
                if cross.segments[index].text.strip()
            ]
            if (
                self._selected_text.strip()
                and (
                    self._page_index not in cross.segments
                    or cross.segments[self._page_index].text != self._selected_text
                )
            ):
                parts.append(self._selected_text)
            return PdfDocument._join_continued_text_parts(parts)
        return self._selected_text

    def _copy_selection(self) -> None:
        text = self._effective_selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _markup_targets(
        self,
    ) -> tuple[int, list[tuple[int, fitz.Rect, tuple[tuple, ...] | None]]] | None:
        if not self._document:
            return None
        cross = self._viewer._cross_page_selection if self._viewer is not None else None
        rects: dict[int, fitz.Rect] = {}
        words_by_page: dict[int, tuple[tuple, ...]] = {}
        if cross is not None:
            for index, segment in cross.segments.items():
                rects[index] = segment.page_rect
                if segment.words:
                    words_by_page[index] = segment.words
        if self._selection_page_rect is not None and self._selected_text.strip():
            rects[self._page_index] = self._selection_page_rect
            if self._selected_words:
                words_by_page[self._page_index] = tuple(self._selected_words)
        if not rects:
            return None
        origin = cross.origin_page_index if cross is not None else self._page_index
        return origin, [
            (index, rects[index], words_by_page.get(index))
            for index in sorted(rects)
        ]

    def _apply_markup(self, kind: str, color_rgb: tuple[float, float, float]) -> bool:
        targets = self._markup_targets()
        if targets is None or not self._document:
            return False
        origin, page_targets = targets
        cross = self._viewer._cross_page_selection if self._viewer is not None else None
        if len(page_targets) == 1 and cross is None:
            page_index, rect, selected_words = page_targets[0]
            if kind == "highlight":
                ok = self._document.set_text_highlight_color(
                    page_index,
                    rect,
                    color_rgb,
                    selected_words=selected_words,
                )
            else:
                ok = self._document.set_text_underline_color(
                    page_index,
                    rect,
                    color_rgb,
                    selected_words=selected_words,
                )
        else:
            ok = self._document.apply_text_markup_to_pages(
                page_targets,
                kind=kind,
                color_rgb=color_rgb,
                origin_page_index=origin,
            )
        if ok:
            self.text_highlight_added.emit()
            self.clear_selection()
        return ok

    def _apply_preferred_text_highlight(self) -> None:
        if self._markup_targets() is None:
            return
        self._apply_markup("highlight", preferred_highlight_rgb())

    def _apply_text_highlight(self, color_id: str) -> None:
        if self._markup_targets() is None:
            return
        rgb = HIGHLIGHT_RGB.get(color_id, HIGHLIGHT_RGB[DEFAULT_HIGHLIGHT_COLOR_ID])
        if self._apply_markup("highlight", rgb):
            set_preferred_highlight_color_id(color_id)

    def _pick_more_highlight_color(self) -> None:
        current = preferred_highlight_rgb()
        default = QColor.fromRgbF(current[0], current[1], current[2])
        chosen = QColorDialog.getColor(default, self, "형광펜 색상 선택")
        if not chosen.isValid():
            return
        rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        if self._apply_markup("highlight", rgb):
            set_preferred_highlight_rgb(rgb)

    def _remove_highlight_selection(self) -> None:
        if not self._document or self._selection_page_rect is None:
            return
        if self._document.remove_text_highlights_in_rect(
            self._page_index,
            self._selection_page_rect,
        ):
            self.text_highlight_added.emit()
            self.clear_selection()

    def _apply_preferred_text_underline(self) -> None:
        if self._markup_targets() is None:
            return
        self._apply_markup("underline", preferred_underline_rgb())

    def _apply_text_underline(self, color_id: str) -> None:
        if self._markup_targets() is None:
            return
        rgb = UNDERLINE_RGB.get(color_id, UNDERLINE_RGB[DEFAULT_UNDERLINE_COLOR_ID])
        if self._apply_markup("underline", rgb):
            set_preferred_underline_color_id(color_id)

    def _pick_more_underline_color(self) -> None:
        current = preferred_underline_rgb()
        default = QColor.fromRgbF(current[0], current[1], current[2])
        chosen = QColorDialog.getColor(default, self, "밑줄 색상 선택")
        if not chosen.isValid():
            return
        rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        if self._apply_markup("underline", rgb):
            set_preferred_underline_rgb(rgb)

    def _remove_underline_selection(self) -> None:
        if not self._document or self._selection_page_rect is None:
            return
        if self._document.remove_text_underlines_in_rect(
            self._page_index,
            self._selection_page_rect,
        ):
            self.text_highlight_added.emit()
            self.clear_selection()

    def _has_next_page(self) -> bool:
        return bool(
            self._document
            and self._page_index < self._document.page_count - 1
        )

    def _can_offer_continue_selection(self) -> bool:
        return bool(self._selected_text.strip() and self._has_next_page())

    def _clear_active_selection(self) -> None:
        self._anchor = None
        self._cursor = None
        self._selection_highlights = []
        self._selection_page_rect = None
        self._selected_text = ""
        self._selected_words = []

    def _commit_current_segment_to_cross_page(self) -> None:
        if (
            not self._viewer
            or not self._document
            or self._selection_page_rect is None
            or not self._selected_text.strip()
        ):
            return
        segment = PageSelectionSegment(
            self._page_index,
            self._selection_page_rect,
            self._selected_text,
            tuple(self._selected_words),
        )
        cross = self._viewer._cross_page_selection
        if cross is None:
            cross = CrossPageSelection(origin_page_index=self._page_index)
            self._viewer._cross_page_selection = cross
        cross.set_segment(segment)

    def _on_continue_selection(self) -> None:
        if self._viewer is not None:
            self._viewer.continue_cross_page_selection(from_canvas=self)

    def _rebuild_stored_segment_highlights(self) -> None:
        self._stored_segment_highlights = []
        if self._viewer is None or self._viewer._cross_page_selection is None:
            return
        segment = self._viewer._cross_page_selection.segments.get(self._page_index)
        if segment is None:
            return
        zoom = self._zoom
        if segment.words:
            self._stored_segment_highlights = [
                QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
                for x, y, w, h in PdfDocument._markup_highlight_rects_from_words(
                    list(segment.words),
                    zoom,
                )
            ]
            return
        page_rect, highlight_rects, _, _ = (
            self._document.get_text_block_selection(
                self._page_index,
                fitz.Point(segment.page_rect.x0, segment.page_rect.y0),
                fitz.Point(segment.page_rect.x1, segment.page_rect.y1),
                zoom,
            )
            if self._document
            else (None, [], "", [])
        )
        if page_rect is None or not highlight_rects:
            page_rect = segment.page_rect
            self._stored_segment_highlights = [
                QRect(
                    int(page_rect.x0 * zoom),
                    int(page_rect.y0 * zoom),
                    max(1, int((page_rect.x1 - page_rect.x0) * zoom)),
                    max(1, int((page_rect.y1 - page_rect.y0) * zoom)),
                )
            ]
            return
        self._stored_segment_highlights = [
            QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
            for x, y, w, h in highlight_rects
        ]

    def _page_point_from_viewport(self, pos: QPoint) -> fitz.Point:
        return fitz.Point(pos.x() / self._zoom, pos.y() / self._zoom)

    def _select_highlight_at(self, pos: QPoint) -> bool:
        if not self._document:
            return False
        selection = self._document.get_text_highlight_selection_at_point(
            self._page_index,
            self._page_point_from_viewport(pos),
        )
        if selection is None:
            return False
        page_rect, quad_rects, selected_text = selection
        if self._viewer is not None:
            self._viewer.clear_cross_page_selection(clear_canvas=False)
        self._selection_page_rect = page_rect
        zoom = self._zoom
        self._selection_highlights = [
            QRect(
                int(rect.x0 * zoom),
                int(rect.y0 * zoom),
                max(1, int((rect.x1 - rect.x0) * zoom)),
                max(1, int((rect.y1 - rect.y0) * zoom)),
            )
            for rect in quad_rects
        ]
        self._selected_text = selected_text
        self.update()
        return True

    def _can_remove_highlight(self) -> bool:
        return bool(
            self._document
            and self._selection_page_rect is not None
            and self._document.has_text_highlight_in_rect(
                self._page_index,
                self._selection_page_rect,
            )
        )

    def _select_markup_at(self, pos: QPoint) -> bool:
        point = self._page_point_from_viewport(pos)
        if self._select_highlight_at(pos):
            self._emit_markup_clicked(point)
            return True
        if self._select_underline_at(pos):
            self._emit_markup_clicked(point)
            return True
        return False

    def _emit_markup_clicked(self, point: fitz.Point) -> None:
        if not self._document:
            return
        entry = self._document.find_text_markup_entry_at_point(self._page_index, point)
        if entry is not None:
            self.markup_clicked.emit(entry)

    def _select_underline_at(self, pos: QPoint) -> bool:
        if not self._document:
            return False
        selection = self._document.get_text_underline_selection_at_point(
            self._page_index,
            self._page_point_from_viewport(pos),
        )
        if selection is None:
            return False
        page_rect, quad_rects, selected_text = selection
        if self._viewer is not None:
            self._viewer.clear_cross_page_selection(clear_canvas=False)
        self._selection_page_rect = page_rect
        zoom = self._zoom
        self._selection_highlights = [
            QRect(
                int(rect.x0 * zoom),
                int(rect.y0 * zoom),
                max(1, int((rect.x1 - rect.x0) * zoom)),
                max(1, int((rect.y1 - rect.y0) * zoom)),
            )
            for rect in quad_rects
        ]
        self._selected_text = selected_text
        self.update()
        return True

    def apply_text_markup_selection(
        self,
        page_rect: fitz.Rect,
        kind: str,
        selected_text: str = "",
    ) -> bool:
        if not self._document or page_rect.is_empty:
            return False
        selection = self._document.get_text_markup_selection_for_rect(
            self._page_index,
            page_rect,
            kind,
        )
        if selection is None:
            return False
        page_rect, quad_rects, text = selection
        self._anchor = None
        self._cursor = None
        self._selection_page_rect = page_rect
        self._selected_text = selected_text or text
        zoom = self._zoom
        self._selection_highlights = [
            QRect(
                int(rect.x0 * zoom),
                int(rect.y0 * zoom),
                max(1, int((rect.x1 - rect.x0) * zoom)),
                max(1, int((rect.y1 - rect.y0) * zoom)),
            )
            for rect in quad_rects
        ]
        self._rebuild_stored_segment_highlights()
        self.update()
        return True

    def _can_remove_underline(self) -> bool:
        return bool(
            self._document
            and self._selection_page_rect is not None
            and self._document.has_text_underline_in_rect(
                self._page_index,
                self._selection_page_rect,
            )
        )

    def remove_selected_highlight(self) -> bool:
        if not self._can_remove_highlight():
            return False
        self._remove_highlight_selection()
        return True

    def remove_selected_underline(self) -> bool:
        if not self._can_remove_underline():
            return False
        self._remove_underline_selection()
        return True

    def try_remove_selected_markup(self) -> bool:
        if self.remove_selected_highlight():
            return True
        return self.remove_selected_underline()

    def _prepare_context_menu_selection(self, pos: QPoint) -> bool:
        if self._effective_selected_text().strip():
            return True
        return self._select_markup_at(pos)

    def _show_text_selection_menu(self, global_pos: QPoint) -> None:
        menu = build_text_selection_context_menu(
            self,
            on_apply_default_highlight=self._apply_preferred_text_highlight,
            on_color_selected=self._apply_text_highlight,
            on_more_colors=self._pick_more_highlight_color,
            on_apply_default_underline=self._apply_preferred_text_underline,
            on_underline_color_selected=self._apply_text_underline,
            on_more_underline_colors=self._pick_more_underline_color,
            on_copy=self._copy_selection,
            on_remove_highlight=self._remove_highlight_selection,
            show_remove_highlight=self._can_remove_highlight(),
            on_remove_underline=self._remove_underline_selection,
            show_remove_underline=self._can_remove_underline(),
            show_continue_selection=self._can_offer_continue_selection(),
            on_continue_selection=self._on_continue_selection,
        )
        menu.exec(global_pos)

    def contextMenuEvent(self, event) -> None:
        if not self._prepare_context_menu_selection(event.pos()):
            return
        self._show_text_selection_menu(event.globalPos())
        event.accept()

    def selection_menu_anchor_global(self) -> QPoint:
        """Global point near the current selection, for opening the markup menu."""
        if self._selection_highlights:
            rect = self._selection_highlights[0]
            return self.mapToGlobal(rect.bottomRight() + QPoint(4, 4))
        if self._selection_page_rect is not None and self._zoom > 0:
            zoom = self._zoom
            point = QPoint(
                int(self._selection_page_rect.x1 * zoom),
                int(self._selection_page_rect.y1 * zoom),
            )
            return self.mapToGlobal(point + QPoint(4, 4))
        return self.mapToGlobal(self.rect().center())

    def _update_selection(self) -> None:
        if (
            not self._document
            or self._anchor is None
            or self._cursor is None
        ):
            self._selection_highlights = []
            self._selection_page_rect = None
            self._selected_text = ""
            self._selected_words = []
            return
        if (self._anchor - self._cursor).manhattanLength() < 4:
            self._selection_highlights = []
            self._selection_page_rect = None
            self._selected_text = ""
            self._selected_words = []
            return

        page_rect, highlight_rects, selected_text, selected_words = (
            self._document.get_text_block_selection(
                self._page_index,
                self._page_point_from_viewport(self._anchor),
                self._page_point_from_viewport(self._cursor),
                self._zoom,
            )
        )
        if page_rect is None:
            self._selection_highlights = []
            self._selection_page_rect = None
            self._selected_text = ""
            self._selected_words = []
            return
        self._selection_page_rect = page_rect
        self._selection_highlights = [
            QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
            for x, y, w, h in highlight_rects
        ]
        self._selected_text = selected_text
        self._selected_words = selected_words

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            if self._viewer is not None and self._viewer._awaiting_continuation:
                if self._anchor is None:
                    self._prime_continuation_anchor()
                self._cursor = event.pos()
                self._update_selection()
                self._viewer._awaiting_continuation = False
                event.accept()
                return
            if self._select_markup_at(event.pos()):
                self._anchor = None
                self._cursor = None
                global_pos = event.globalPosition().toPoint()
                QTimer.singleShot(
                    0,
                    lambda pos=global_pos: self._show_text_selection_menu(pos),
                )
                event.accept()
                return
            if self._viewer is not None:
                self._viewer.clear_cross_page_selection(clear_canvas=False)
                self._viewer.clear_other_canvas_selection(self)
            self._anchor = event.pos()
            self._cursor = event.pos()
            self._update_selection()
            self.update()
            self.grabMouse()
        super().mousePressEvent(event)

    def _prime_continuation_anchor(self) -> None:
        if not self._document:
            return
        page = self._document._doc[self._page_index]
        words = page.get_text("words")
        if not words:
            self._anchor = QPoint(0, 0)
            return
        first = min(
            words,
            key=lambda word: (
                PdfDocument._word_line_id(word),
                PdfDocument._word_sort_key(word),
            ),
        )
        x0, y0, _, _ = first[:4]
        self._anchor = QPoint(int(x0 * self._zoom), int(y0 * self._zoom))

    def mouseMoveEvent(self, event) -> None:
        if self._anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._cursor = event.pos()
            self._update_selection()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.mouseGrabber() == self:
            self.releaseMouse()
        if event.button() == Qt.MouseButton.LeftButton and self._anchor is not None:
            self._cursor = event.pos()
            self._update_selection()
            self._anchor = None
            self.update()
            if self._effective_selected_text().strip():
                # Defer popup: menu.exec during mouseRelease (after grab) can
                # abort on Windows, especially with the two-page spread host.
                global_pos = event.globalPosition().toPoint()
                QTimer.singleShot(
                    0,
                    lambda pos=global_pos: self._show_text_selection_menu(pos),
                )
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._document is not None:
            if self.mouseGrabber() == self:
                self.releaseMouse()
            self._anchor = None
            self._cursor = None
            self.clear_selection(clear_cross_page=True)
            if self._viewer is not None and self._viewer.begin_text_edit(
                event.pos(),
                page_index=self._page_index,
            ):
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if (
            not self._text_highlights
            and not self._text_underlines
            and not self._search_highlights
            and not self._selection_highlights
            and not self._stored_segment_highlights
        ):
            return
        painter = QPainter(self)
        if self._text_highlights:
            painter.setPen(Qt.PenStyle.NoPen)
            for rect, color in self._text_highlights:
                painter.setBrush(color)
                painter.drawRect(rect)
        if self._text_underlines:
            for line, color in self._text_underlines:
                x0, y0, x1, y1 = line
                pen = QPen(color)
                pen.setWidth(max(1, int(round(2 * self._zoom))))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(x0), int(y1), int(x1), int(y1))
        if self._search_highlights:
            painter.setPen(Qt.PenStyle.NoPen)
            for index, rect in enumerate(self._search_highlights):
                if index == self._active_search_highlight:
                    painter.setBrush(QColor(255, 152, 0, 150))
                else:
                    painter.setBrush(QColor(255, 235, 59, 110))
                painter.drawRect(rect)
        if self._stored_segment_highlights or self._selection_highlights:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(51, 153, 255, 70))
            for rect in self._stored_segment_highlights:
                painter.drawRect(rect)
            painter.setBrush(QColor(51, 153, 255, 90))
            for rect in self._selection_highlights:
                painter.drawRect(rect)
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_C
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self._effective_selected_text()
        ):
            self._copy_selection()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            if self._can_remove_highlight():
                self._remove_highlight_selection()
                event.accept()
                return
            if self._can_remove_underline():
                self._remove_underline_selection()
                event.accept()
                return
        super().keyPressEvent(event)


class PageViewer(QWidget):
    """Right pane: scrollable page preview and bottom navigation bar."""

    page_changed = pyqtSignal(int)
    text_highlight_added = pyqtSignal()
    text_edited = pyqtSignal()
    markup_clicked = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PdfDocument | None = None
        self._current_index = 0
        self._zoom = 1.0
        self._fit_mode: str | None = "page"
        self._fit_zoom_scale = 1.0
        self._search_page_rects: list[fitz.Rect] = []
        self._search_active_index = -1
        self._cross_page_selection: CrossPageSelection | None = None
        self._awaiting_continuation = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.preview_stack = QStackedWidget()
        preview_bg = f"background-color: {PREVIEW_BACKGROUND};"

        empty_page = QWidget()
        empty_page.setStyleSheet(preview_bg)
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        self.empty_hint = QLabel(EMPTY_PREVIEW_HINT)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: #666666; font-size: 14px;")
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addStretch(1)
        self.preview_stack.addWidget(empty_page)

        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ {preview_bg} border: none; }}"
            + PREVIEW_SCROLLBAR_STYLE
        )
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        viewport = self.scroll_area.viewport()
        viewport.setStyleSheet(preview_bg)
        viewport.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        viewport.installEventFilter(self)

        self._scroll_anim = QPropertyAnimation(
            self.scroll_area.verticalScrollBar(), b"value", self
        )
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.setDuration(SMOOTH_SCROLL_DURATION_MS)
        self._scroll_target: int | None = None

        self._facing_mode = False
        self._search_page_index = -1
        self._rendering = False

        self._spread_host = QWidget()
        self._spread_host.setStyleSheet(f"background-color: {PREVIEW_BACKGROUND};")
        # Manual placement avoids QLayout + setFixedSize feedback with QScrollArea.
        self.page_canvas = PageCanvas(self._spread_host)
        self.page_canvas.set_page_viewer(self)
        self.page_canvas.text_highlight_added.connect(self._on_canvas_highlight_added)
        self.page_canvas.text_edited.connect(self._on_canvas_text_edited)
        self.page_canvas.markup_clicked.connect(self._on_canvas_markup_clicked)

        self.page_canvas_right = PageCanvas(self._spread_host)
        self.page_canvas_right.set_page_viewer(self)
        self.page_canvas_right.setVisible(False)
        self.page_canvas_right.text_highlight_added.connect(self._on_canvas_highlight_added)
        self.page_canvas_right.text_edited.connect(self._on_canvas_text_edited)
        self.page_canvas_right.markup_clicked.connect(self._on_canvas_markup_clicked)

        self._inline_editor: _InlineTextEditor | None = None
        self._text_edit_ctx: dict | None = None
        self._text_edit_active = False
        self.scroll_area.setWidget(self._spread_host)
        self.preview_stack.addWidget(self.scroll_area)
        self.preview_stack.setStyleSheet(preview_bg)
        root.addWidget(self.preview_stack, 1)

        self._log_section = QWidget()
        self._log_section.setVisible(False)
        self._log_expanded = True
        log_section_layout = QVBoxLayout(self._log_section)
        log_section_layout.setContentsMargins(0, 0, 0, 0)
        log_section_layout.setSpacing(0)

        self._log_header = QWidget()
        self._log_header.setObjectName("logHeader")
        self._log_header.setFixedHeight(_LOG_HEADER_HEIGHT)
        self._log_header.setStyleSheet(_LOG_HEADER_STYLE)
        log_header_layout = QHBoxLayout(self._log_header)
        log_header_layout.setContentsMargins(4, 0, 8, 0)
        log_header_layout.setSpacing(0)

        self._log_tab_btn = QPushButton("▼  터미널")
        self._log_tab_btn.setFlat(True)
        self._log_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_tab_btn.setStyleSheet(_LOG_TAB_STYLE)
        self._log_tab_btn.clicked.connect(self._toggle_log_panel)
        log_header_layout.addWidget(self._log_tab_btn, 0, Qt.AlignmentFlag.AlignLeft)
        log_header_layout.addStretch(1)

        self._log_close_btn = QPushButton("×")
        self._log_close_btn.setFlat(True)
        self._log_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_close_btn.setToolTip("터미널 닫기")
        self._log_close_btn.setStyleSheet(_LOG_CLOSE_STYLE)
        self._log_close_btn.clicked.connect(self.hide_log_panel)
        log_header_layout.addWidget(self._log_close_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMinimumHeight(_LOG_BODY_MIN_HEIGHT)
        self.log_panel.setMaximumHeight(_LOG_BODY_MAX_HEIGHT)
        log_font = QFont("Consolas")
        if not log_font.family():
            log_font = QFont("Courier New")
        log_font.setPointSize(10)
        self.log_panel.setFont(log_font)
        self.log_panel.setStyleSheet(
            "QPlainTextEdit {"
            "background-color: #1e1e1e;"
            "color: #d4d4d4;"
            "border: none;"
            "padding: 6px;"
            "}"
        )

        log_section_layout.addWidget(self._log_header)
        log_section_layout.addWidget(self.log_panel)
        root.addWidget(self._log_section)

        self.status_bar = self._build_status_bar()
        root.addWidget(self.status_bar)

        self._busy_overlay = QLabel(self.preview_stack)
        self._busy_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._busy_overlay.setWordWrap(True)
        self._busy_overlay.setStyleSheet(
            "background-color: rgba(255, 255, 255, 210);"
            "color: #333333; font-size: 15px; font-weight: bold;"
            "border: 1px solid #c8c8c8; border-radius: 8px; padding: 20px;"
        )
        self._busy_overlay.hide()
        self._busy_base_message = ""
        self._busy_progress = 0

    def show_busy_message(self, message: str) -> None:
        self._busy_base_message = message
        self._busy_progress = 0
        self._refresh_busy_overlay()

    def update_busy_progress(self, percent: int) -> None:
        self._busy_progress = max(0, min(100, percent))
        self._refresh_busy_overlay()

    def hide_busy_message(self) -> None:
        self._busy_overlay.hide()

    def _toggle_log_panel(self) -> None:
        self._log_expanded = not self._log_expanded
        self.log_panel.setVisible(self._log_expanded)
        self._log_tab_btn.setText(
            "▼  터미널" if self._log_expanded else "▶  터미널"
        )

    def show_log_panel(self) -> None:
        self.log_panel.clear()
        self._log_expanded = True
        self.log_panel.setVisible(True)
        self._log_tab_btn.setText("▼  터미널")
        self._log_section.setVisible(True)

    def hide_log_panel(self) -> None:
        self._log_section.setVisible(False)

    def append_log_line(self, text: str) -> None:
        self.log_panel.appendPlainText(text)
        scrollbar = self.log_panel.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        QApplication.processEvents()

    def _refresh_busy_overlay(self) -> None:
        self._busy_overlay.setText(self._busy_base_message)
        self._busy_overlay.setGeometry(self.preview_stack.rect())
        self._busy_overlay.show()
        self._busy_overlay.raise_()
        QApplication.processEvents()

    def set_document(self, document: PdfDocument | None) -> None:
        self._document = document
        self._current_index = 0
        self._fit_mode = "page"
        self._fit_zoom_scale = 1.0
        self._zoom = 1.0
        self.clear_cross_page_selection()
        self.refresh()
        if document and document.page_count > 0:
            self.fit_page_when_ready()

    def fit_page_when_ready(self) -> None:
        """Apply page fit after layout so the viewport has its final size."""
        self.fit_page()
        QTimer.singleShot(0, self.fit_page)

    def facing_mode(self) -> bool:
        return self._facing_mode

    def set_facing_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._facing_mode == enabled:
            return
        self._facing_mode = enabled
        if not enabled:
            self.page_canvas_right.clear_selection(clear_cross_page=False)
            self.page_canvas_right.setVisible(False)
            self.page_canvas_right.setPixmap(QPixmap())
            self.page_canvas_right.setFixedSize(0, 0)
        elif self._document and self._document.page_count > 0:
            self._current_index = self._normalize_page_index(self._current_index)
        self.refresh()
        if self._fit_mode:
            QTimer.singleShot(0, self._render_current_page)

    def _page_step(self) -> int:
        return 2 if self._facing_mode else 1

    def _normalize_page_index(self, index: int) -> int:
        if not self._document or self._document.page_count == 0:
            return 0
        index = max(0, min(index, self._document.page_count - 1))
        if self._facing_mode:
            index -= index % 2
        return index

    def _right_page_index(self) -> int | None:
        if not self._facing_mode or not self._document:
            return None
        right = self._current_index + 1
        if right >= self._document.page_count:
            return None
        return right

    def go_previous_page(self, *, scroll_to_bottom: bool = False) -> None:
        self.set_current_index(
            self._current_index - self._page_step(),
            scroll_to_bottom=scroll_to_bottom,
        )

    def go_next_page(self) -> None:
        self.set_current_index(self._current_index + self._page_step())

    def _visible_canvases(self) -> list[PageCanvas]:
        canvases = [self.page_canvas]
        if self._facing_mode and self.page_canvas_right.isVisible():
            canvases.append(self.page_canvas_right)
        return canvases

    def _canvas_for_page(self, page_index: int) -> PageCanvas | None:
        if page_index == self._current_index:
            return self.page_canvas
        right = self._right_page_index()
        if right is not None and page_index == right:
            return self.page_canvas_right
        return None

    def clear_other_canvas_selection(self, keep: PageCanvas) -> None:
        for canvas in self._visible_canvases():
            if canvas is keep:
                continue
            canvas._anchor = None
            canvas._cursor = None
            canvas._selection_highlights = []
            canvas._selection_page_rect = None
            canvas._selected_text = ""
            canvas._selected_words = []
            canvas.update()

    def _on_canvas_highlight_added(self) -> None:
        self._apply_text_highlights_overlay()
        self.text_highlight_added.emit()

    def _on_canvas_text_edited(self) -> None:
        self.refresh()
        self.text_edited.emit()

    def _on_canvas_markup_clicked(self, entry: object) -> None:
        self.markup_clicked.emit(entry)

    def current_index(self) -> int:
        return self._current_index

    def try_remove_selected_highlight(self) -> bool:
        for canvas in self._visible_canvases():
            if canvas.try_remove_selected_markup():
                return True
        return False

    def select_markup_entry(self, entry: TextMarkupEntry) -> None:
        if not self._document:
            return
        target_page = entry.page_index
        preserve_cross_page = entry.group_id is not None
        if entry.group_id:
            segments = self._document.collect_text_markup_group_segments(
                entry.group_id,
                entry.kind,
            )
            if not segments:
                return
            self._cross_page_selection = CrossPageSelection(
                origin_page_index=entry.page_index,
            )
            for segment in segments:
                self._cross_page_selection.set_segment(segment)
            self._awaiting_continuation = False
        else:
            self.clear_cross_page_selection(clear_canvas=False)

        visible_right = self._right_page_index()
        already_visible = target_page == self._current_index or (
            visible_right is not None and target_page == visible_right
        )
        if not already_visible:
            self.set_current_index(target_page, preserve_cross_page=preserve_cross_page)
        elif preserve_cross_page:
            self.refresh()
        else:
            canvas = self._canvas_for_page(target_page) or self.page_canvas
            canvas._anchor = None
            canvas._cursor = None
            canvas._selection_highlights = []
            canvas._selection_page_rect = None
            canvas._selected_text = ""
            canvas._selected_words = []
            canvas._rebuild_stored_segment_highlights()
            canvas.update()

        target_canvas = self._canvas_for_page(target_page) or self.page_canvas
        if entry.group_id and self._cross_page_selection is not None:
            segment = self._cross_page_selection.segments.get(target_page)
            if segment is not None:
                target_canvas.apply_text_markup_selection(
                    segment.page_rect,
                    entry.kind,
                    segment.text,
                )
                return
        if entry.page_rect is not None:
            target_canvas.apply_text_markup_selection(
                entry.page_rect,
                entry.kind,
                entry.text,
            )

    def show_selection_context_menu(
        self,
        global_pos: QPoint | None = None,
        *,
        page_index: int | None = None,
    ) -> None:
        """Open the text/markup action menu for the current selection."""
        canvas: PageCanvas | None = None
        if page_index is not None:
            canvas = self._canvas_for_page(page_index)
        if canvas is None:
            for candidate in self._visible_canvases():
                if (
                    candidate._effective_selected_text().strip()
                    or candidate._selection_page_rect is not None
                ):
                    canvas = candidate
                    break
        if canvas is None:
            canvas = self.page_canvas
        if not (
            canvas._effective_selected_text().strip()
            or canvas._selection_page_rect is not None
        ):
            return
        anchor = global_pos if global_pos is not None else canvas.selection_menu_anchor_global()
        QTimer.singleShot(0, lambda: canvas._show_text_selection_menu(anchor))

    def clear_cross_page_selection(self, *, clear_canvas: bool = True) -> None:
        self._cross_page_selection = None
        self._awaiting_continuation = False
        if clear_canvas:
            for canvas in (self.page_canvas, self.page_canvas_right):
                canvas._stored_segment_highlights = []
                canvas.update()

    def continue_cross_page_selection(
        self,
        from_canvas: PageCanvas | None = None,
    ) -> None:
        canvas = from_canvas or self.page_canvas
        if not canvas._can_offer_continue_selection():
            return
        canvas._commit_current_segment_to_cross_page()
        canvas._clear_active_selection()
        canvas.update()
        next_page = canvas._page_index + 1
        self._awaiting_continuation = True
        right = self._right_page_index()
        if (
            self._facing_mode
            and right is not None
            and next_page == right
            and self.page_canvas_right.isVisible()
        ):
            QTimer.singleShot(
                0,
                lambda: self._prime_continuation_on(self.page_canvas_right),
            )
            return
        self.set_current_index(next_page, preserve_cross_page=True)

    def _prime_continuation_selection(self) -> None:
        self._prime_continuation_on(self.page_canvas)

    def _prime_continuation_on(self, canvas: PageCanvas) -> None:
        canvas._prime_continuation_anchor()
        canvas._cursor = canvas._anchor
        canvas._update_selection()
        canvas.update()

    def set_current_index(
        self,
        index: int,
        *,
        preserve_cross_page: bool = False,
        scroll_to_bottom: bool = False,
    ) -> None:
        if not self._document or self._document.page_count == 0:
            return
        index = self._normalize_page_index(index)
        if index != self._current_index:
            self._cancel_text_edit()
            self._stop_scroll_animation()
            if not preserve_cross_page:
                self.clear_cross_page_selection()
            self._current_index = index
            self.scroll_area.horizontalScrollBar().setValue(0)
            self.scroll_area.verticalScrollBar().setValue(0)
            self.refresh()
            if scroll_to_bottom:
                self._scroll_to_page_bottom()
            self.page_changed.emit(index)
            if self._awaiting_continuation:
                QTimer.singleShot(0, self._prime_continuation_selection)
        elif preserve_cross_page:
            self.refresh()
            if self._awaiting_continuation:
                QTimer.singleShot(0, self._prime_continuation_selection)

    def set_zoom_percent(self, percent: float) -> None:
        target = max(0.1, min(percent / 100.0, MAX_ZOOM))
        if self._fit_mode:
            base = self._base_fit_zoom()
            self._fit_zoom_scale = target / base if base > 0 else 1.0
        else:
            self._zoom = target
        self._sync_zoom_controls()
        self._render_current_page()

    def _scale_zoom(self, factor: float) -> None:
        self.set_zoom_percent(self._current_display_zoom() * 100 * factor)

    def fit_width(self) -> None:
        self._fit_zoom_scale = 1.0
        self._fit_mode = "width"
        self._render_current_page()

    def fit_height(self) -> None:
        self._fit_zoom_scale = 1.0
        self._fit_mode = "height"
        self._render_current_page()

    def fit_page(self) -> None:
        self._fit_zoom_scale = 1.0
        self._fit_mode = "page"
        self._render_current_page()

    def rotate_view_cw(self) -> None:
        if self._document and self._document.page_count > 0:
            self._document.rotate_pages([self._current_index], 90)
            self.refresh()

    def rotate_view_ccw(self) -> None:
        if self._document and self._document.page_count > 0:
            self._document.rotate_pages([self._current_index], -90)
            self.refresh()

    def refresh(self) -> None:
        self._update_page_info()
        self._render_current_page()

    def _ensure_inline_editor(self, canvas: PageCanvas) -> _InlineTextEditor:
        editor = self._inline_editor
        if editor is None:
            editor = _InlineTextEditor(canvas)
            editor.setStyleSheet(
                "QLineEdit {"
                " background: #ffffff;"
                " border: 1px solid #4a90d9;"
                " padding: 0px 2px;"
                " color: #000000;"
                " selection-background-color: #4a90d9;"
                " }"
            )
            editor.commit_requested.connect(self._commit_text_edit)
            editor.cancel_requested.connect(self._cancel_text_edit)
            editor.editingFinished.connect(self._on_editor_focus_lost)
            editor.hide()
            self._inline_editor = editor
        else:
            editor.setParent(canvas)
        return editor

    def begin_text_edit(
        self,
        canvas_pos: QPoint,
        *,
        page_index: int | None = None,
    ) -> bool:
        if not self._document or self._document.page_count == 0:
            return False
        zoom = self._effective_zoom()
        if zoom <= 0:
            return False
        page = self._current_index if page_index is None else page_index
        canvas = self._canvas_for_page(page) or self.page_canvas
        page_x = canvas_pos.x() / zoom
        page_y = canvas_pos.y() / zoom
        info = self._document.find_text_line_at(page, page_x, page_y)
        if not info:
            return False

        self._cancel_text_edit()
        editor = self._ensure_inline_editor(canvas)
        ctx = dict(info)
        ctx["page_index"] = page
        self._text_edit_ctx = ctx

        x0, y0, x1, y1 = info["rect"]
        left = int(round(x0 * zoom)) - 3
        top = int(round(y0 * zoom)) - 2
        width = max(48, int(round((x1 - x0) * zoom)) + 16)
        height = max(20, int(round((y1 - y0) * zoom)) + 8)

        font = QFont(editor.font())
        font.setPixelSize(max(6, int(round(info["size"] * zoom))))
        editor.setFont(font)
        editor.setText(info["text"])
        editor.setGeometry(left, top, width, height)
        editor.show()
        editor.raise_()
        editor.setFocus()
        editor.selectAll()
        self._text_edit_active = True
        return True

    def _on_editor_focus_lost(self) -> None:
        if self._text_edit_active:
            self._commit_text_edit()

    def _commit_text_edit(self) -> None:
        if not self._text_edit_active:
            return
        self._text_edit_active = False
        ctx = self._text_edit_ctx
        editor = self._inline_editor
        new_text = editor.text() if editor is not None else ""
        if editor is not None:
            editor.hide()
        self._text_edit_ctx = None
        if not ctx or not self._document:
            return
        if new_text == ctx["text"]:
            return
        ok = self._document.overwrite_text_line(
            ctx["page_index"],
            ctx["rect"],
            ctx["origin"],
            new_text,
            ctx["size"],
            ctx["color"],
        )
        if ok:
            self.text_edited.emit()
            self.refresh()

    def _cancel_text_edit(self) -> None:
        if not self._text_edit_active:
            return
        self._text_edit_active = False
        self._text_edit_ctx = None
        if self._inline_editor is not None:
            self._inline_editor.hide()

    def clear_search_highlights(self) -> None:
        self._search_page_rects = []
        self._search_active_index = -1
        self._search_page_index = -1
        for canvas in (self.page_canvas, self.page_canvas_right):
            canvas.clear_search_highlights()

    def show_search_result(
        self,
        page_index: int,
        page_rects: list[fitz.Rect],
        active_index_on_page: int,
        *,
        focus_rect: fitz.Rect | None = None,
    ) -> None:
        self._search_page_rects = page_rects
        self._search_active_index = active_index_on_page
        self._search_page_index = page_index
        if not self._document or self._document.page_count == 0:
            return
        page_index = max(0, min(page_index, self._document.page_count - 1))
        self._search_page_index = page_index
        right = self._right_page_index()
        already_visible = page_index == self._current_index or (
            right is not None and page_index == right
        )
        if not already_visible:
            self._cancel_text_edit()
            self._stop_scroll_animation()
            self._current_index = self._normalize_page_index(page_index)
            self.scroll_area.verticalScrollBar().setValue(0)
            self.scroll_area.horizontalScrollBar().setValue(0)
            self._update_page_info()
            self._render_current_page()
            self.page_changed.emit(self._current_index)
        else:
            self._apply_search_highlights()
        if focus_rect is not None:
            self.reveal_page_rect(focus_rect, page_index=page_index)

    def reveal_page_rect(
        self,
        rect: fitz.Rect,
        *,
        page_index: int | None = None,
    ) -> None:
        page = (
            self._search_page_index
            if page_index is None and self._search_page_index >= 0
            else (self._current_index if page_index is None else page_index)
        )
        canvas = self._canvas_for_page(page) or self.page_canvas
        zoom = self._effective_zoom()
        origin = canvas.pos()
        x = origin.x() + int(rect.x0 * zoom)
        y = origin.y() + int(rect.y0 * zoom)
        w = max(1, int((rect.x1 - rect.x0) * zoom))
        h = max(1, int((rect.y1 - rect.y0) * zoom))
        margin = 40
        self.scroll_area.ensureVisible(x, y, margin, margin)
        self.scroll_area.ensureVisible(x + w, y + h, margin, margin)

    def _apply_search_highlights(self) -> None:
        for canvas in (self.page_canvas, self.page_canvas_right):
            canvas.clear_search_highlights()
        if not self._search_page_rects:
            return
        page = self._search_page_index if self._search_page_index >= 0 else self._current_index
        canvas = self._canvas_for_page(page)
        if canvas is None:
            return
        zoom = self._effective_zoom()
        highlights = [
            QRect(
                int(rect.x0 * zoom),
                int(rect.y0 * zoom),
                max(1, int((rect.x1 - rect.x0) * zoom)),
                max(1, int((rect.y1 - rect.y0) * zoom)),
            )
            for rect in self._search_page_rects
        ]
        canvas.set_search_highlights(highlights, self._search_active_index)

    def _apply_text_highlights_overlay(self) -> None:
        if not self._document or self._document.page_count == 0:
            self.page_canvas.set_text_highlights([])
            self.page_canvas.set_text_underlines([])
            self.page_canvas_right.set_text_highlights([])
            self.page_canvas_right.set_text_underlines([])
            return
        zoom = self._effective_zoom()
        pages = [self._current_index]
        right = self._right_page_index()
        if right is not None:
            pages.append(right)
        for page in pages:
            canvas = self._canvas_for_page(page)
            if canvas is None:
                continue
            highlight_overlays: list[tuple[QRect, QColor]] = []
            for rect, rgb in self._document.get_page_text_highlight_overlays(page, zoom):
                highlight_overlays.append(
                    (
                        QRect(
                            int(rect.x0),
                            int(rect.y0),
                            max(1, int(rect.x1 - rect.x0)),
                            max(1, int(rect.y1 - rect.y0)),
                        ),
                        highlight_qcolor_from_rgb(rgb),
                    )
                )
            underline_overlays: list[tuple[tuple[float, float, float, float], QColor]] = []
            for line, rgb in self._document.get_page_text_underline_overlays(page, zoom):
                underline_overlays.append((line, markup_qcolor_from_rgb(rgb)))
            canvas.set_text_highlights(highlight_overlays)
            canvas.set_text_underlines(underline_overlays)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if (
            self._document
            and self._document.page_count > 0
            and self._fit_mode
        ):
            self._render_current_page()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._busy_overlay.isHidden():
            self._busy_overlay.setGeometry(self.preview_stack.rect())
        if self._fit_mode and not self._rendering:
            # Defer so scrollbar show/hide from spread size does not re-enter render.
            QTimer.singleShot(0, self._render_current_page_if_fitting)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.scroll_area.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                self.scroll_area.viewport().setFocus()
            elif event.type() == QEvent.Type.Wheel:
                wheel = event
                if self._handle_preview_wheel(
                    wheel.angleDelta().y(),
                    wheel.modifiers(),
                ):
                    event.accept()
                    return True
                return False
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._document or self._document.page_count == 0:
            super().keyPressEvent(event)
            return

        key = event.key()
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier

        if ctrl and shift and key == Qt.Key.Key_Left:
            self.set_current_index(0)
            event.accept()
            return
        if ctrl and shift and key == Qt.Key.Key_Right:
            self._go_last()
            event.accept()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            step = (
                self.scroll_area.verticalScrollBar().pageStep()
                if key == Qt.Key.Key_PageUp
                else ARROW_SCROLL_STEP
            )
            self._handle_preview_wheel(step, Qt.KeyboardModifier.NoModifier)
            event.accept()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            step = (
                self.scroll_area.verticalScrollBar().pageStep()
                if key == Qt.Key.Key_PageDown
                else ARROW_SCROLL_STEP
            )
            self._handle_preview_wheel(-step, Qt.KeyboardModifier.NoModifier)
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self.go_previous_page(scroll_to_bottom=True)
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self.go_next_page()
            event.accept()
            return

        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._handle_preview_wheel(event.angleDelta().y(), event.modifiers()):
            event.accept()
            return
        super().wheelEvent(event)

    def _has_vertical_scroll(self) -> bool:
        return self.scroll_area.verticalScrollBar().maximum() > 0

    def _stop_scroll_animation(self) -> None:
        if self._scroll_anim.state() == QPropertyAnimation.State.Running:
            self._scroll_anim.stop()
        self._scroll_target = None

    def _effective_scroll_value(self) -> int:
        """Current scroll target while animating, else the live bar value."""
        if (
            self._scroll_target is not None
            and self._scroll_anim.state() == QPropertyAnimation.State.Running
        ):
            return self._scroll_target
        return self.scroll_area.verticalScrollBar().value()

    def _scroll_vertically(self, delta_y: int) -> None:
        bar = self.scroll_area.verticalScrollBar()
        base = self._effective_scroll_value()
        target = max(bar.minimum(), min(bar.maximum(), base - delta_y))
        if target == bar.value():
            self._stop_scroll_animation()
            return
        self._scroll_target = target
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()

    def _scroll_to_page_bottom(self) -> None:
        self._stop_scroll_animation()
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def scroll_by_key(self, *, up: bool, page: bool) -> None:
        """Scroll mode navigation: scroll within a page, turn at boundaries.

        When crossing to the previous page, the previous page is shown from its
        bottom so it scrolls upward into view.
        """
        step = (
            self.scroll_area.verticalScrollBar().pageStep()
            if page
            else ARROW_SCROLL_STEP
        )
        self._handle_preview_wheel(step if up else -step, Qt.KeyboardModifier.NoModifier)

    def _change_page_by_wheel(self, delta_y: int) -> bool:
        if not self._document or self._document.page_count == 0:
            return False
        step = self._page_step()
        if delta_y > 0 and self._current_index > 0:
            self.set_current_index(
                self._current_index - step,
                scroll_to_bottom=True,
            )
            return True
        last_left = self._normalize_page_index(self._document.page_count - 1)
        if delta_y < 0 and self._current_index < last_left:
            self.set_current_index(self._current_index + step)
            return True
        return False

    def _handle_preview_wheel(self, delta_y: int, modifiers: Qt.KeyboardModifier) -> bool:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            factor = ZOOM_STEP_FACTOR if delta_y > 0 else 1.0 / ZOOM_STEP_FACTOR
            self._scale_zoom(factor)
            return True
        if not self._document or self._document.page_count == 0:
            return False
        if self._has_vertical_scroll():
            bar = self.scroll_area.verticalScrollBar()
            position = self._effective_scroll_value()
            at_top = position <= bar.minimum()
            at_bottom = position >= bar.maximum()
            if (delta_y > 0 and at_top) or (delta_y < 0 and at_bottom):
                if self._change_page_by_wheel(delta_y):
                    return True
            self._scroll_vertically(int(delta_y * WHEEL_SCROLL_MULTIPLIER))
            return True
        return self._change_page_by_wheel(delta_y)

    def _apply_scroll_resize_mode(self) -> None:
        self.scroll_area.setWidgetResizable(False)

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(3)
        self._status_layout = layout

        compact_btn = 24
        btn_height = 22
        nav_icon_size = QSize(18, 14)
        arrow_icon_size = QSize(14, 14)

        self.size_label = QLabel("")
        layout.addWidget(self.size_label)
        self._status_lead_stretch_index = layout.count()
        layout.addStretch(1)

        self.btn_first = QPushButton()
        self.btn_first.setIcon(_edge_nav_icon(True))
        self.btn_first.setIconSize(nav_icon_size)
        self.btn_first.setFixedSize(compact_btn, btn_height)
        self.btn_first.setToolTip("맨 앞 페이지")
        self.btn_first.clicked.connect(lambda: self.set_current_index(0))
        layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(_arrow_nav_icon(True))
        self.btn_prev.setIconSize(arrow_icon_size)
        self.btn_prev.setFixedSize(compact_btn, btn_height)
        self.btn_prev.setToolTip("이전 페이지")
        self.btn_prev.clicked.connect(
            lambda: self.go_previous_page(scroll_to_bottom=True)
        )
        layout.addWidget(self.btn_prev)

        self.page_spin = QSpinBox()
        self.page_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setFixedWidth(80)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.valueChanged.connect(self._on_page_spin_changed)
        layout.addWidget(self.page_spin)

        self.total_label = QLabel("/ 0")
        layout.addWidget(self.total_label)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(_arrow_nav_icon(False))
        self.btn_next.setIconSize(arrow_icon_size)
        self.btn_next.setFixedSize(compact_btn, btn_height)
        self.btn_next.setToolTip("다음 페이지")
        self.btn_next.clicked.connect(self.go_next_page)
        layout.addWidget(self.btn_next)

        self.btn_last = QPushButton()
        self.btn_last.setIcon(_edge_nav_icon(False))
        self.btn_last.setIconSize(nav_icon_size)
        self.btn_last.setFixedSize(compact_btn, btn_height)
        self.btn_last.setToolTip("마지막 페이지")
        self.btn_last.clicked.connect(self._go_last)
        layout.addWidget(self.btn_last)

        layout.addSpacing(6)

        self.btn_fit_width = QPushButton("너비")
        self.btn_fit_width.setFixedSize(36, btn_height)
        self.btn_fit_width.setToolTip("너비 맞추기")
        self.btn_fit_width.clicked.connect(self.fit_width)
        layout.addWidget(self.btn_fit_width)

        self.btn_fit_height = QPushButton("높이")
        self.btn_fit_height.setFixedSize(36, btn_height)
        self.btn_fit_height.setToolTip("높이 맞추기")
        self.btn_fit_height.clicked.connect(self.fit_height)
        layout.addWidget(self.btn_fit_height)

        self.btn_fit_page = QPushButton("화면")
        self.btn_fit_page.setFixedSize(36, btn_height)
        self.btn_fit_page.setToolTip("화면 맞추기")
        self.btn_fit_page.clicked.connect(self.fit_page)
        layout.addWidget(self.btn_fit_page)

        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedSize(compact_btn, btn_height)
        self.btn_zoom_out.clicked.connect(
            lambda: self._scale_zoom(1.0 / ZOOM_STEP_FACTOR)
        )
        layout.addWidget(self.btn_zoom_out)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(10)
        self.zoom_slider.setMaximum(MAX_ZOOM_PERCENT)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(88)
        self.zoom_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.zoom_slider)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(compact_btn, btn_height)
        self.btn_zoom_in.clicked.connect(
            lambda: self._scale_zoom(ZOOM_STEP_FACTOR)
        )
        layout.addWidget(self.btn_zoom_in)

        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setFixedWidth(76)
        for value in ZOOM_PRESETS:
            self.zoom_combo.addItem(f"{value}%", value)
        self.zoom_combo.setCurrentText("100%")
        line_edit = self.zoom_combo.lineEdit()
        if line_edit is not None:
            line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            line_edit.setMinimumWidth(52)
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_combo_changed)
        layout.addWidget(self.zoom_combo)

        self._status_trail_stretch_index = layout.count()
        layout.addStretch(0)

        return bar

    def set_status_bar_centered(self, centered: bool) -> None:
        """Center the bottom controls (used in full-screen); hide the size label."""
        self.size_label.setVisible(not centered)
        self._status_layout.setStretch(self._status_trail_stretch_index, 1 if centered else 0)

    def _go_last(self) -> None:
        if self._document:
            self.set_current_index(self._document.page_count - 1)

    def _on_page_spin_changed(self, value: int) -> None:
        self.set_current_index(value - 1)

    def _on_slider_changed(self, value: int) -> None:
        self.set_zoom_percent(float(value))

    def _on_zoom_combo_changed(self, text: str) -> None:
        cleaned = text.replace("%", "").strip()
        if not cleaned:
            return
        try:
            percent = float(cleaned)
        except ValueError:
            return
        self.set_zoom_percent(percent)

    def _current_display_zoom(self) -> float:
        """Zoom shown in controls; matches fit modes when active."""
        return self._effective_zoom()

    def _base_fit_zoom(self) -> float:
        if not self._document or self._document.page_count == 0:
            return 1.0
        left = self._document.get_page_rect(self._current_index)
        content_w = left.width
        content_h = left.height
        gap_px = 0
        if self._facing_mode:
            right_index = self._current_index + 1
            if right_index < self._document.page_count:
                right = self._document.get_page_rect(right_index)
                content_w = left.width + right.width
                content_h = max(left.height, right.height)
                gap_px = SPREAD_GAP_PX
        viewport = self.scroll_area.viewport().size()
        margin = 24
        if self._fit_mode == "width":
            return max(0.1, (viewport.width() - margin - gap_px) / content_w)
        if self._fit_mode == "height":
            return max(0.1, (viewport.height() - margin) / content_h)
        if self._fit_mode == "page":
            width_fit = (viewport.width() - margin - gap_px) / content_w
            height_fit = (viewport.height() - margin) / content_h
            return max(0.1, min(width_fit, height_fit))
        return self._zoom

    def _effective_zoom(self) -> float:
        if self._fit_mode:
            return min(self._base_fit_zoom() * self._fit_zoom_scale, MAX_ZOOM)
        return min(self._zoom, MAX_ZOOM)

    def _sync_zoom_controls(self, skip_slider: bool = False) -> None:
        percent = int(round(self._current_display_zoom() * 100))
        if not skip_slider:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(max(10, min(MAX_ZOOM_PERCENT, percent)))
            self.zoom_slider.blockSignals(False)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{percent}%")
        self.zoom_combo.blockSignals(False)

    def _update_size_label(self) -> None:
        if not self._document or self._document.page_count == 0:
            self.size_label.setText("")
            return
        w, h = self._document.get_page_size_cm(self._current_index)
        creation_dpi = self._document.get_page_creation_dpi(self._current_index)
        if creation_dpi is None:
            self.size_label.setText(f"{w} x {h} cm")
        else:
            self.size_label.setText(f"{w} x {h} cm  {creation_dpi} DPI")

    def _update_page_info(self) -> None:
        total = self._document.page_count if self._document else 0
        has_pages = total > 0
        self.page_spin.blockSignals(True)
        self.page_spin.setEnabled(has_pages)
        self.page_spin.setMaximum(max(1, total))
        if has_pages:
            self.page_spin.setValue(self._current_index + 1)
        self.page_spin.blockSignals(False)
        right = self._right_page_index() if has_pages else None
        if right is not None:
            self.total_label.setText(f"– {right + 1} / {total}")
        else:
            self.total_label.setText(f"/ {total}")
        if self._facing_mode:
            self.btn_prev.setToolTip("이전 스프레드")
            self.btn_next.setToolTip("다음 스프레드")
        else:
            self.btn_prev.setToolTip("이전 페이지")
            self.btn_next.setToolTip("다음 페이지")
        for btn in (
            self.btn_first,
            self.btn_prev,
            self.btn_next,
            self.btn_last,
            self.btn_fit_width,
            self.btn_fit_height,
            self.btn_fit_page,
            self.btn_zoom_in,
            self.btn_zoom_out,
        ):
            btn.setEnabled(has_pages)

        self._update_size_label()

    def _update_preview_stack(self) -> None:
        has_pages = bool(self._document and self._document.page_count > 0)
        self.preview_stack.setCurrentIndex(1 if has_pages else 0)

    def _render_current_page_if_fitting(self) -> None:
        if self._fit_mode and not self._rendering:
            self._render_current_page()

    def _sync_spread_host_size(self) -> None:
        left_w = max(0, self.page_canvas.width())
        left_h = max(0, self.page_canvas.height())
        self.page_canvas.move(0, 0)
        if self.page_canvas_right.isVisible():
            right_w = max(0, self.page_canvas_right.width())
            right_h = max(0, self.page_canvas_right.height())
            host_h = max(left_h, right_h)
            self.page_canvas.move(0, max(0, (host_h - left_h) // 2))
            self.page_canvas_right.move(
                left_w + SPREAD_GAP_PX,
                max(0, (host_h - right_h) // 2),
            )
            self._spread_host.setFixedSize(
                left_w + SPREAD_GAP_PX + right_w,
                host_h,
            )
        else:
            self.page_canvas_right.move(0, 0)
            self._spread_host.setFixedSize(left_w, left_h)

    def _render_current_page(self) -> None:
        if self._rendering:
            return
        self._rendering = True
        try:
            self._apply_scroll_resize_mode()
            if not self._document or self._document.page_count == 0:
                self.page_canvas.clear()
                self.page_canvas.setPixmap(QPixmap())
                self.page_canvas.setFixedSize(0, 0)
                self.page_canvas.clear_selection()
                self.page_canvas_right.clear_selection(clear_cross_page=False)
                self.page_canvas_right.setPixmap(QPixmap())
                self.page_canvas_right.setFixedSize(0, 0)
                self.page_canvas_right.setVisible(False)
                self._spread_host.setFixedSize(0, 0)
                self._update_preview_stack()
                return
            if self._document.rendering_paused:
                return

            zoom = self._effective_zoom()
            if self._fit_mode is None:
                self._zoom = zoom
            self._sync_zoom_controls()

            preserve_selection = (
                self._awaiting_continuation or self._cross_page_selection is not None
            )
            pix = self._document.render_page_pixmap(self._current_index, zoom)
            self.page_canvas.set_content(
                pixmap_from_fitz(pix),
                self._document,
                self._current_index,
                zoom,
                clear_selection=not preserve_selection,
            )

            right_index = self._right_page_index()
            if right_index is not None:
                right_pix = self._document.render_page_pixmap(right_index, zoom)
                self.page_canvas_right.setVisible(True)
                self.page_canvas_right.set_content(
                    pixmap_from_fitz(right_pix),
                    self._document,
                    right_index,
                    zoom,
                    clear_selection=not preserve_selection,
                )
            else:
                self.page_canvas_right.clear_selection(clear_cross_page=False)
                self.page_canvas_right.setPixmap(QPixmap())
                self.page_canvas_right.setFixedSize(0, 0)
                self.page_canvas_right.setVisible(False)

            self._sync_spread_host_size()
            self._apply_search_highlights()
            self._apply_text_highlights_overlay()
            self._update_preview_stack()
        finally:
            self._rendering = False
