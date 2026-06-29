"""Main page viewer with zoom and navigation controls."""

from __future__ import annotations

import fitz
from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QKeyEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
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

from pdf_editor.document import PdfDocument
from pdf_editor.pixmap_utils import pixmap_from_fitz

ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 250]
MAX_ZOOM = 2.5
PREVIEW_BACKGROUND = "#efefef"
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


class PageCanvas(QLabel):
    """Rendered page with drag-to-select text overlay."""

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
        self._highlights: list[QRect] = []
        self._selected_text = ""
        self._search_highlights: list[QRect] = []
        self._active_search_highlight = -1

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
            self.clear_selection()

    def clear_selection(self) -> None:
        self._anchor = None
        self._cursor = None
        self._highlights = []
        self._selected_text = ""
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
        return self._selected_text

    def _copy_selection(self) -> None:
        if self._selected_text:
            QApplication.clipboard().setText(self._selected_text)

    def contextMenuEvent(self, event) -> None:
        if not self._selected_text:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("복사")
        copy_action.triggered.connect(self._copy_selection)
        menu.exec(event.globalPos())
        event.accept()

    def _page_rect_from_points(self, start: QPoint, end: QPoint) -> fitz.Rect:
        zoom = self._zoom
        return fitz.Rect(
            min(start.x(), end.x()) / zoom,
            min(start.y(), end.y()) / zoom,
            max(start.x(), end.x()) / zoom,
            max(start.y(), end.y()) / zoom,
        )

    def _update_selection(self) -> None:
        if (
            not self._document
            or self._anchor is None
            or self._cursor is None
        ):
            self._highlights = []
            self._selected_text = ""
            return
        if (self._anchor - self._cursor).manhattanLength() < 4:
            self._highlights = []
            self._selected_text = ""
            return

        page_rect = self._page_rect_from_points(self._anchor, self._cursor)
        self._highlights = [
            QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
            for x, y, w, h in self._document.get_word_highlight_rects(
                self._page_index,
                page_rect,
                self._zoom,
            )
        ]
        self._selected_text = self._document.get_text_in_rect(
            self._page_index,
            page_rect,
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._anchor = event.pos()
            self._cursor = event.pos()
            self._update_selection()
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._cursor = event.pos()
            self._update_selection()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._anchor is not None:
            self._cursor = event.pos()
            self._update_selection()
            self._anchor = None
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._search_highlights and not self._highlights:
            return
        painter = QPainter(self)
        if self._search_highlights:
            painter.setPen(Qt.PenStyle.NoPen)
            for index, rect in enumerate(self._search_highlights):
                if index == self._active_search_highlight:
                    painter.setBrush(QColor(255, 152, 0, 150))
                else:
                    painter.setBrush(QColor(255, 235, 59, 110))
                painter.drawRect(rect)
        if self._highlights:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(51, 153, 255, 90))
            for rect in self._highlights:
                painter.drawRect(rect)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_C
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self._selected_text
        ):
            self._copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)


class PageViewer(QWidget):
    """Right pane: scrollable page preview and bottom navigation bar."""

    page_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PdfDocument | None = None
        self._current_index = 0
        self._zoom = 1.0
        self._fit_mode: str | None = "page"
        self._uniform_zoom: float | None = None
        self._pending_uniform_zoom_lock = False
        self._initial_fit_scale: float | None = None
        self._search_page_rects: list[fitz.Rect] = []
        self._search_active_index = -1

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
        )
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        viewport = self.scroll_area.viewport()
        viewport.setStyleSheet(preview_bg)
        viewport.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        viewport.installEventFilter(self)

        self.page_canvas = PageCanvas()
        self.scroll_area.setWidget(self.page_canvas)
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
        self._uniform_zoom = None
        self._pending_uniform_zoom_lock = bool(document and document.page_count > 0)
        self.refresh()
        if document and document.page_count > 0:
            self.fit_page_when_ready()

    def fit_page_when_ready(self) -> None:
        """Apply page fit after layout so the viewport has its final size."""
        self.fit_page()
        QTimer.singleShot(0, self.fit_page)

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int) -> None:
        if not self._document or self._document.page_count == 0:
            return
        index = max(0, min(index, self._document.page_count - 1))
        if index != self._current_index:
            self._current_index = index
            self.scroll_area.verticalScrollBar().setValue(0)
            self.scroll_area.horizontalScrollBar().setValue(0)
            self.refresh()
            self.page_changed.emit(index)

    def set_zoom_percent(self, percent: float) -> None:
        self._initial_fit_scale = None
        self._uniform_zoom = None
        self._pending_uniform_zoom_lock = False
        self._fit_mode = None
        self._zoom = max(0.1, min(percent / 100.0, MAX_ZOOM))
        self._sync_zoom_controls()
        self._render_current_page()

    def fit_width(self) -> None:
        self._initial_fit_scale = None
        self._uniform_zoom = None
        self._pending_uniform_zoom_lock = False
        self._fit_mode = "width"
        self._render_current_page()

    def fit_height(self) -> None:
        self._initial_fit_scale = None
        self._uniform_zoom = None
        self._pending_uniform_zoom_lock = False
        self._fit_mode = "height"
        self._render_current_page()

    def fit_page(self) -> None:
        self._initial_fit_scale = None
        self._uniform_zoom = None
        self._pending_uniform_zoom_lock = True
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

    def clear_search_highlights(self) -> None:
        self._search_page_rects = []
        self._search_active_index = -1
        self.page_canvas.clear_search_highlights()

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
        if not self._document or self._document.page_count == 0:
            return
        page_index = max(0, min(page_index, self._document.page_count - 1))
        if page_index != self._current_index:
            self._current_index = page_index
            self.scroll_area.verticalScrollBar().setValue(0)
            self.scroll_area.horizontalScrollBar().setValue(0)
            self._update_page_info()
            self._render_current_page()
            self.page_changed.emit(page_index)
        else:
            self._apply_search_highlights()
        if focus_rect is not None:
            self.reveal_page_rect(focus_rect)

    def reveal_page_rect(self, rect: fitz.Rect) -> None:
        zoom = self._effective_zoom()
        x = int(rect.x0 * zoom)
        y = int(rect.y0 * zoom)
        w = max(1, int((rect.x1 - rect.x0) * zoom))
        h = max(1, int((rect.y1 - rect.y0) * zoom))
        margin = 40
        self.scroll_area.ensureVisible(x, y, margin, margin)
        self.scroll_area.ensureVisible(x + w, y + h, margin, margin)

    def _apply_search_highlights(self) -> None:
        if not self._search_page_rects:
            self.page_canvas.clear_search_highlights()
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
        self.page_canvas.set_search_highlights(
            highlights,
            self._search_active_index,
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if (
            self._document
            and self._document.page_count > 0
            and (self._fit_mode or self._pending_uniform_zoom_lock)
        ):
            self._render_current_page()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._busy_overlay.isHidden():
            self._busy_overlay.setGeometry(self.preview_stack.rect())
        if self._fit_mode:
            self._render_current_page()

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
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.set_current_index(self._current_index - 1)
            event.accept()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.set_current_index(self._current_index + 1)
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

    def _scroll_vertically(self, delta_y: int) -> None:
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.value() - delta_y)

    def _change_page_by_wheel(self, delta_y: int) -> bool:
        if not self._document or self._document.page_count == 0:
            return False
        if delta_y > 0 and self._current_index > 0:
            self.set_current_index(self._current_index - 1)
            return True
        if delta_y < 0 and self._current_index < self._document.page_count - 1:
            self.set_current_index(self._current_index + 1)
            return True
        return False

    def _handle_preview_wheel(self, delta_y: int, modifiers: Qt.KeyboardModifier) -> bool:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            step = 10 if delta_y > 0 else -10
            self.set_zoom_percent(self._current_display_zoom() * 100 + step)
            return True
        if not self._document or self._document.page_count == 0:
            return False
        if self._has_vertical_scroll():
            bar = self.scroll_area.verticalScrollBar()
            at_top = bar.value() <= bar.minimum()
            at_bottom = bar.value() >= bar.maximum()
            if (delta_y > 0 and at_top) or (delta_y < 0 and at_bottom):
                if self._change_page_by_wheel(delta_y):
                    return True
            self._scroll_vertically(delta_y)
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

        compact_btn = 24
        btn_height = 22
        nav_icon_size = QSize(18, 14)
        arrow_icon_size = QSize(14, 14)

        self.size_label = QLabel("")
        layout.addWidget(self.size_label)
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
        self.btn_prev.clicked.connect(lambda: self.set_current_index(self._current_index - 1))
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
        self.btn_next.clicked.connect(lambda: self.set_current_index(self._current_index + 1))
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
            lambda: self.set_zoom_percent(self._current_display_zoom() * 100 - 10)
        )
        layout.addWidget(self.btn_zoom_out)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(10)
        self.zoom_slider.setMaximum(250)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(88)
        self.zoom_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.zoom_slider)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(compact_btn, btn_height)
        self.btn_zoom_in.clicked.connect(
            lambda: self.set_zoom_percent(self._current_display_zoom() * 100 + 10)
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

        return bar

    def _go_last(self) -> None:
        if self._document:
            self.set_current_index(self._document.page_count - 1)

    def _on_page_spin_changed(self, value: int) -> None:
        self.set_current_index(value - 1)

    def _on_slider_changed(self, value: int) -> None:
        self._initial_fit_scale = None
        self._uniform_zoom = None
        self._pending_uniform_zoom_lock = False
        if self._fit_mode is not None:
            self._fit_mode = None
        self._zoom = min(value / 100.0, MAX_ZOOM)
        self._sync_zoom_controls(skip_slider=True)
        self._render_current_page()

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
        if self._fit_mode:
            return self._effective_zoom()
        if self._uniform_zoom is not None:
            return self._uniform_zoom
        return self._zoom

    def _sync_zoom_controls(self, skip_slider: bool = False) -> None:
        percent = int(round(self._current_display_zoom() * 100))
        if not skip_slider:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(max(10, min(250, percent)))
            self.zoom_slider.blockSignals(False)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{percent}%")
        self.zoom_combo.blockSignals(False)

    def _update_page_info(self) -> None:
        total = self._document.page_count if self._document else 0
        has_pages = total > 0
        self.page_spin.blockSignals(True)
        self.page_spin.setEnabled(has_pages)
        self.page_spin.setMaximum(max(1, total))
        if has_pages:
            self.page_spin.setValue(self._current_index + 1)
        self.page_spin.blockSignals(False)
        self.total_label.setText(f"/ {total}")
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

        if has_pages and self._document:
            w, h = self._document.get_page_size_cm(self._current_index)
            self.size_label.setText(f"{w} x {h} cm")
        else:
            self.size_label.setText("")

    def _effective_zoom(self) -> float:
        if not self._document or self._document.page_count == 0:
            return 1.0
        rect = self._document.get_page_rect(self._current_index)
        viewport = self.scroll_area.viewport().size()
        margin = 24
        if self._uniform_zoom is not None:
            return min(self._uniform_zoom, MAX_ZOOM)
        if self._fit_mode == "width":
            fit = min(max(0.1, (viewport.width() - margin) / rect.width), MAX_ZOOM)
        elif self._fit_mode == "height":
            fit = min(max(0.1, (viewport.height() - margin) / rect.height), MAX_ZOOM)
        elif self._fit_mode == "page":
            width_fit = (viewport.width() - margin) / rect.width
            height_fit = (viewport.height() - margin) / rect.height
            fit = min(max(0.1, min(width_fit, height_fit)), MAX_ZOOM)
        else:
            return min(self._zoom, MAX_ZOOM)
        return fit

    def _update_preview_stack(self) -> None:
        has_pages = bool(self._document and self._document.page_count > 0)
        self.preview_stack.setCurrentIndex(1 if has_pages else 0)

    def _render_current_page(self) -> None:
        self._apply_scroll_resize_mode()
        if not self._document or self._document.page_count == 0:
            self.page_canvas.clear()
            self.page_canvas.setPixmap(QPixmap())
            self.page_canvas.setFixedSize(0, 0)
            self.page_canvas.clear_selection()
            self._update_preview_stack()
            return
        if self._document.rendering_paused:
            return

        zoom = self._effective_zoom()
        if self._pending_uniform_zoom_lock:
            self._uniform_zoom = zoom
            self._fit_mode = None
            self._zoom = zoom
            self._pending_uniform_zoom_lock = False
            zoom = self._uniform_zoom
        elif self._fit_mode is None and self._uniform_zoom is None:
            self._zoom = zoom
        elif self._uniform_zoom is not None:
            zoom = self._uniform_zoom
        self._sync_zoom_controls()

        pix = self._document.render_page_pixmap(self._current_index, zoom)
        pixmap = pixmap_from_fitz(pix)
        self.page_canvas.set_content(
            pixmap,
            self._document,
            self._current_index,
            zoom,
        )
        self._apply_search_highlights()
        self._update_preview_stack()
