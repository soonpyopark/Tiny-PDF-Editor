"""Thumbnail sidebar with page list and drag-and-drop."""

from __future__ import annotations

from collections import OrderedDict

from PyQt6.QtCore import QPoint, QRect, QSize, QEvent, QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QRubberBand,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import PdfDocument
from pdf_editor.page_clipboard import PageClipboard
from pdf_editor.pixmap_utils import pixmap_from_fitz

THUMB_ROLE = Qt.ItemDataRole.UserRole + 1
THUMB_EMPTY_HINT = "Drag & Drop files here."
THUMB_SCALE_LEVELS = (55, 95, 135, 165)
DEFAULT_THUMB_SCALE_LEVEL = (len(THUMB_SCALE_LEVELS) + 1) // 2
DEFAULT_THUMB_SCALE = THUMB_SCALE_LEVELS[DEFAULT_THUMB_SCALE_LEVEL - 1]
THUMB_CACHE_MAX = 50
THUMB_KEEP_BUFFER = 3
PAGE_MOVE_MIME = "application/x-pdf-editor-page-indices"
_CHILD_STYLE = "background: transparent; border: none;"
_THUMB_MARGIN = 6
_THUMB_SPACING = 4
_THUMB_LABEL_HEIGHT = 20
THUMB_ITEM_GAP = 20
_PANEL_HEADER_MIN_WIDTH = 212
_PANEL_EDGE_PADDING = 12
DROP_INDICATOR_COLOR = QColor("#f28b82")
DROP_INDICATOR_WIDTH = 2
DROP_INDICATOR_TICK = 7
THUMB_BORDER_COLOR = "#666666"
THUMB_CURRENT_BORDER_COLOR = "#f28b82"
THUMB_SELECTED_BORDER_COLOR = "#d93025"
_RANGE_SELECT_SCROLL_MARGIN = 28
_RANGE_SELECT_SCROLL_STEP = 8
_RANGE_SELECT_SCROLL_MAX_STEP = 44
_RANGE_SELECT_SCROLL_MS = 30
_RUBBER_BAND_FILL = QColor(242, 139, 130, 50)
_RUBBER_BAND_BORDER = QColor("#f28b82")


def _menu_action_text(label: str, standard_key: QKeySequence.StandardKey) -> str:
    """Show shortcut in menu label without registering a duplicate QAction shortcut."""
    seq = QKeySequence(standard_key)
    return f"{label}\t{seq.toString(QKeySequence.SequenceFormat.NativeText)}"


def thumb_scale_for_level(level: int) -> int:
    """Return pixel width for 1-based level (1..4)."""
    index = max(1, min(len(THUMB_SCALE_LEVELS), level)) - 1
    return THUMB_SCALE_LEVELS[index]


def thumb_level_for_scale(scale: int) -> int:
    """Return nearest 1-based level for a pixel width."""
    best_level = 1
    best_diff = abs(THUMB_SCALE_LEVELS[0] - scale)
    for index, value in enumerate(THUMB_SCALE_LEVELS, start=1):
        diff = abs(value - scale)
        if diff < best_diff:
            best_diff = diff
            best_level = index
    return best_level


class ThumbnailItemWidget(QWidget):
    """Single thumbnail cell."""

    def __init__(
        self,
        pixmap: QPixmap,
        page_number: int,
        thumb_scale: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._thumb_scale = max(32, thumb_scale)
        self._thumb_bounds = QSize(self._thumb_scale, max(45, int(self._thumb_scale * 1.4)))
        self._selected = False
        self._current = False
        self._list_row = 0
        self._column_width: int | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(_CHILD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_THUMB_MARGIN, _THUMB_MARGIN, _THUMB_MARGIN, _THUMB_MARGIN)
        layout.setSpacing(_THUMB_SPACING)

        self._thumb_area = QWidget()
        self._thumb_area.setStyleSheet(_CHILD_STYLE)
        self._thumb_area.setAutoFillBackground(False)
        self._thumb_area.setFixedSize(self._thumb_bounds)
        self._thumb_area.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._image = QLabel(self._thumb_area)
        self._image.setStyleSheet(_CHILD_STYLE)
        self._image.setFrameShape(QFrame.Shape.NoFrame)
        self._image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._thumb_area, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._page_label = QLabel(str(page_number))
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._page_label.setFrameShape(QFrame.Shape.NoFrame)
        self._page_label.setFixedHeight(_THUMB_LABEL_HEIGHT)
        self._page_label.setStyleSheet(_CHILD_STYLE)
        self._page_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._page_label)

        self.set_pixmap(pixmap)
        self.set_selected(False)
        self._apply_cell_size()

    @classmethod
    def cell_size(cls, thumb_scale: int) -> QSize:
        thumb_scale = max(32, thumb_scale)
        thumb_h = max(45, int(thumb_scale * 1.4))
        width = thumb_scale + _THUMB_MARGIN * 2
        height = _THUMB_MARGIN * 2 + thumb_h + _THUMB_SPACING + _THUMB_LABEL_HEIGHT
        return QSize(width, height)

    @classmethod
    def list_grid_size(cls, thumb_scale: int) -> QSize:
        """Grid cell size includes vertical gap below each thumbnail box."""
        cell = cls.cell_size(thumb_scale)
        return QSize(cell.width(), cell.height() + THUMB_ITEM_GAP)

    def sizeHint(self) -> QSize:
        base = self.cell_size(self._thumb_scale)
        width = max(base.width(), self._column_width or 0)
        return QSize(width, base.height())

    def set_column_width(self, width: int) -> None:
        self._column_width = width
        self._apply_cell_size()

    def _card_rect(self) -> QRect:
        """Visible thumbnail card bounds (matches paintEvent border)."""
        cell = self.cell_size(self._thumb_scale)
        x = max(0, (self.width() - cell.width()) // 2)
        return QRect(x + 1, 1, cell.width() - 2, self.height() - 2)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = self.cell_size(self._thumb_scale)
        x = max(0, (self.width() - cell.width()) // 2)
        rect = QRect(x + 1, 1, cell.width() - 2, self.height() - 2)
        if self._selected:
            painter.setBrush(QColor("#ebebeb"))
        else:
            painter.setBrush(QColor("#ffffff"))
        painter.setPen(
            QPen(QColor(self._border_color()), 1)
        )
        painter.drawRoundedRect(rect, 4, 4)
        painter.end()
        super().paintEvent(event)

    def pixmap(self) -> QPixmap:
        return self._image.pixmap() or QPixmap()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self._thumb_bounds,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image.setPixmap(scaled)
        self._image.setGeometry(
            (self._thumb_bounds.width() - scaled.width()) // 2,
            (self._thumb_bounds.height() - scaled.height()) // 2,
            scaled.width(),
            scaled.height(),
        )

    def set_thumb_scale(self, thumb_scale: int) -> None:
        self._thumb_scale = max(32, thumb_scale)
        self._thumb_bounds = QSize(self._thumb_scale, max(45, int(self._thumb_scale * 1.4)))
        self._thumb_area.setFixedSize(self._thumb_bounds)
        current = self.pixmap()
        if not current.isNull():
            self.set_pixmap(current)
        self._apply_cell_size()

    def _apply_cell_size(self) -> None:
        self.setFixedSize(self.sizeHint())
        self.updateGeometry()

    def set_page_number(self, page_number: int) -> None:
        self._page_label.setText(str(page_number))

    def list_row(self) -> int:
        return self._list_row

    def set_list_row(self, row: int) -> None:
        self._list_row = row

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def _border_color(self) -> str:
        if self._selected:
            return THUMB_SELECTED_BORDER_COLOR
        if self._current:
            return THUMB_CURRENT_BORDER_COLOR
        return THUMB_BORDER_COLOR

    def set_current(self, current: bool) -> None:
        self._current = current
        self.update()


class _DropIndicatorOverlay(QWidget):
    """Drop insertion line drawn above thumbnail items."""

    def __init__(self, list_widget: ThumbnailListWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._list = list_widget
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()

    def sync_geometry(self) -> None:
        viewport = self._list.viewport()
        self.setGeometry(viewport.rect())
        if self.isVisible():
            self.raise_()

    def show_for_index(self, index: int | None) -> None:
        self.sync_geometry()
        if index is None:
            self.hide()
            return
        self.show()
        self.update()

    def paintEvent(self, event) -> None:
        index = self._list._drop_indicator_index
        if index is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y, x1, x2 = self._list._indicator_geometry(index)
        self._list._paint_drop_indicator(painter, y, x1, x2)
        painter.end()
        super().paintEvent(event)


class _ThumbnailListDelegate(QStyledItemDelegate):
    """Hide Qt's default list-item focus rectangle."""

    def paint(self, painter, option, index) -> None:
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class ThumbnailListWidget(QListWidget):
    """List widget with multi-select, reorder drag, and file drop."""

    drop_at_index = pyqtSignal(int, list)
    pages_move_requested = pyqtSignal(int, list)
    context_action = pyqtSignal(str)
    paste_at_index = pyqtSignal(int)
    paste_anchor_changed = pyqtSignal(int)
    scale_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSpacing(0)
        self.setUniformItemSizes(True)
        self.setIconSize(self.iconSize())
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self._drop_overlay = _DropIndicatorOverlay(self, self.viewport())
        self._rubber_band_widget = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._rubber_band_widget.setStyleSheet(
            "QRubberBand {"
            f" background-color: rgba({_RUBBER_BAND_FILL.red()}, {_RUBBER_BAND_FILL.green()},"
            f" {_RUBBER_BAND_FILL.blue()}, {_RUBBER_BAND_FILL.alpha()});"
            f" border: 1px solid {_RUBBER_BAND_BORDER.name()};"
            " }"
        )
        self.viewport().installEventFilter(self)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setItemDelegate(_ThumbnailListDelegate(self))
        self.setStyleSheet(
            """
            QListWidget {
                outline: none;
                border: none;
            }
            QListWidget:focus {
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item:selected,
            QListWidget::item:hover,
            QListWidget::item:focus,
            QListWidget::item:selected:focus {
                background: transparent;
                border: none;
                outline: none;
            }
            """
        )
        self.setToolTip("페이지를 드래그해 순서를 바꾸거나, 파일을 끌어다 놓으세요")
        self._drop_indicator_index: int | None = None
        self._history_state = lambda: (False, False)
        self._drag_start_indices: list[int] = []
        self._block_selection_sync = False
        self._pending_click_row: int | None = None
        self._pending_click_modifiers = Qt.KeyboardModifier.NoModifier
        self._anchor_index = 0
        self._range_select_active = False
        self._range_select_anchor = 0
        self._range_select_modifiers = Qt.KeyboardModifier.NoModifier
        self._range_select_cursor_global = QPoint()
        self._range_select_end_row = 0
        self._rubber_band_pending = False
        self._rubber_band_active = False
        self._rubber_band_origin_content = QPoint()
        self._rubber_band_current = QPoint()
        self._rubber_band_modifiers = Qt.KeyboardModifier.NoModifier
        self._card_press_row: int | None = None
        self._card_press_modifiers = Qt.KeyboardModifier.NoModifier
        self._card_press_origin_global = QPoint()
        self._card_press_drag_started = False
        self._page_reorder_drag_active = False
        self._page_reorder_drag_vp_pos = QPoint()
        self._page_reorder_drop_index = 0
        self._drag_autoscroll_dir = 0
        self._drag_autoscroll_speed = _RANGE_SELECT_SCROLL_STEP
        self._drag_autoscroll_vp_pos = QPoint()
        self._drag_autoscroll_timer = QTimer(self)
        self._drag_autoscroll_timer.setInterval(_RANGE_SELECT_SCROLL_MS)
        self._drag_autoscroll_timer.timeout.connect(self._drag_autoscroll_step)
        self._thumb_level = DEFAULT_THUMB_SCALE_LEVEL
        self._thumb_scale = thumb_scale_for_level(self._thumb_level)
        self._last_column_width = -1
        self._layout_in_progress = False
        self._pending_column_layout = False
        self.configure_grid(self._thumb_scale)
        self.itemSelectionChanged.connect(self._sync_selection_visuals)
        self.currentRowChanged.connect(self._sync_selection_visuals)

    @staticmethod
    def column_width_for(thumb_scale: int) -> int:
        return ThumbnailItemWidget.cell_size(thumb_scale).width() + _PANEL_EDGE_PADDING

    def _column_width(self) -> int:
        cell_w = ThumbnailItemWidget.cell_size(self._thumb_scale).width()
        vp_w = self.viewport().width()
        return max(cell_w, vp_w) if vp_w > 0 else cell_w

    def _apply_column_layout(self) -> None:
        if self._layout_in_progress:
            return
        column_w = self._column_width()
        if column_w == self._last_column_width:
            return
        self._layout_in_progress = True
        try:
            grid_h = ThumbnailItemWidget.list_grid_size(self._thumb_scale).height()
            self.setGridSize(QSize(column_w, grid_h))
            self._last_column_width = column_w
            for row in range(self.count()):
                item = self.item(row)
                widget = self.itemWidget(item)
                if item and isinstance(widget, ThumbnailItemWidget):
                    widget.set_column_width(column_w)
                    size = widget.sizeHint()
                    widget.setFixedSize(size)
                    item.setSizeHint(size)
            self.doItemsLayout()
        finally:
            self._layout_in_progress = False

    def _schedule_column_layout(self) -> None:
        if self._pending_column_layout:
            return
        self._pending_column_layout = True
        QTimer.singleShot(0, self._run_scheduled_column_layout)

    def _run_scheduled_column_layout(self) -> None:
        self._pending_column_layout = False
        if self._column_width() != self._last_column_width:
            self._apply_column_layout()

    def _show_drop_indicator(self, index: int | None) -> None:
        self._drop_indicator_index = index
        self._drop_overlay.show_for_index(index)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._drop_overlay.sync_geometry()
        self._schedule_column_layout()

    def configure_grid(self, thumb_scale: int) -> None:
        self._thumb_scale = thumb_scale
        self._thumb_level = thumb_level_for_scale(thumb_scale)
        self.setWrapping(False)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self._last_column_width = -1
        self._apply_column_layout()

    def set_thumb_level(self, level: int) -> None:
        self._thumb_level = max(1, min(len(THUMB_SCALE_LEVELS), level))
        self._thumb_scale = thumb_scale_for_level(self._thumb_level)
        self.configure_grid(self._thumb_scale)

    def set_thumbnail_size(self, size: int) -> None:
        self.configure_grid(size)
        self.setIconSize(self.iconSize().__class__(size, int(size * 1.4)))
        self._sync_item_widget_geometry()

    def _sync_item_widget_geometry(self) -> None:
        """QListWidget item widgets must be resized manually when the cell grows."""
        self._last_column_width = -1
        self._apply_column_layout()

    def _refresh_item_sizes(self) -> None:
        self._sync_item_widget_geometry()

    def update_item_pixmap(self, row: int, pixmap: QPixmap) -> None:
        item = self.item(row)
        widget = self.itemWidget(item)
        if item and isinstance(widget, ThumbnailItemWidget):
            widget.set_pixmap(pixmap)
            size = widget.sizeHint()
            widget.setFixedSize(size)
            item.setSizeHint(size)

    def visible_rows(self) -> list[int]:
        viewport_rect = self.viewport().rect()
        visible: list[int] = []
        for row in range(self.count()):
            item = self.item(row)
            if item and viewport_rect.intersects(self.visualItemRect(item)):
                visible.append(row)
        return visible

    def selected_indices(self) -> list[int]:
        return sorted(self.row(item) for item in self.selectedItems())

    def clear_all_selection(self) -> None:
        self._block_selection_sync = True
        self.clearSelection()
        self._block_selection_sync = False
        self._sync_selection_visuals()

    def clear_selection_except_current(self) -> None:
        """Deselect all pages except the one shown in the preview."""
        current = self.currentRow()
        self._block_selection_sync = True
        self.clearSelection()
        if 0 <= current < self.count():
            item = self.item(current)
            if item:
                item.setSelected(True)
            self._anchor_index = current
        self._block_selection_sync = False
        self._sync_selection_visuals()

    def select_all_pages(self) -> None:
        self._block_selection_sync = True
        for row in range(self.count()):
            item = self.item(row)
            if item:
                item.setSelected(True)
        self._block_selection_sync = False
        if self.count() > 0:
            self._anchor_index = self.currentRow() if self.currentRow() >= 0 else 0
        self._sync_selection_visuals()

    def scroll_to_row(self, row: int) -> None:
        if 0 <= row < self.count():
            item = self.item(row)
            if item:
                self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

    def _set_focus_row(self, row: int) -> None:
        """Keep current row and shift-click anchor aligned after list mutations."""
        if 0 <= row < self.count():
            self.setCurrentRow(row)
            self._anchor_index = row

    def set_item_widget(self, row: int, pixmap: QPixmap, page_number: int) -> None:
        item = self.item(row)
        if not item:
            return

        widget = ThumbnailItemWidget(pixmap, page_number, self._thumb_scale)
        widget.set_list_row(row)
        self.setItemWidget(item, widget)
        widget.set_column_width(self._column_width())
        size = widget.sizeHint()
        widget.setFixedSize(size)
        item.setSizeHint(size)

    def _grab_tracking_mouse(self) -> None:
        self.viewport().grabMouse()

    def _release_mouse_if_grabbed(self) -> None:
        grabber = QWidget.mouseGrabber()
        if grabber is self.viewport():
            self.viewport().releaseMouse()
        elif grabber is self:
            self.releaseMouse()

    def _tracking_mouse_grabbed(self) -> bool:
        grabber = QWidget.mouseGrabber()
        return grabber is self or grabber is self.viewport()

    def _on_thumb_pressed(
        self,
        row: int,
        modifiers: Qt.KeyboardModifier,
        global_pos: QPoint,
    ) -> None:
        self._card_press_row = row
        self._card_press_modifiers = modifiers
        self._card_press_origin_global = global_pos
        self._card_press_drag_started = False
        self._pending_click_row = row
        self._pending_click_modifiers = modifiers
        self._grab_tracking_mouse()

    def _reset_card_press(self) -> None:
        self._card_press_row = None
        self._card_press_modifiers = Qt.KeyboardModifier.NoModifier
        self._card_press_drag_started = False
        self._pending_click_row = None
        self._pending_click_modifiers = Qt.KeyboardModifier.NoModifier

    def _handle_card_press_move(self, global_pos: QPoint) -> bool:
        """Return True when a page-reorder drag starts from the thumbnail card."""
        if self._card_press_row is None or self._card_press_drag_started:
            return False
        delta = global_pos - self._card_press_origin_global
        if delta.manhattanLength() < QApplication.startDragDistance():
            return False
        self._card_press_drag_started = True
        row = self._card_press_row
        modifiers = self._card_press_modifiers
        if row not in self.selected_indices():
            self._apply_item_click(row, modifiers)
        self._start_page_drag_from_row(row)
        self._reset_card_press()
        return True

    def _row_at_pos(self, pos: QPoint) -> int:
        if self.count() == 0:
            return 0
        item = self.itemAt(pos)
        if item is not None:
            return self.row(item)
        ordered = self._items_in_reading_order()
        if pos.y() < ordered[0][1].center().y():
            return ordered[0][0]
        for row, rect in ordered:
            if pos.y() <= rect.bottom():
                return row
        return ordered[-1][0]

    def _content_y_scroll(self) -> int:
        return self.verticalScrollBar().value()

    def _viewport_to_content(self, vp_pos: QPoint) -> QPoint:
        return QPoint(vp_pos.x(), vp_pos.y() + self._content_y_scroll())

    def _resolve_range_select_end_row(self, vp_pos: QPoint) -> int:
        """Map cursor position to a row; extend through visible rows while auto-scrolling."""
        candidate = self._row_at_pos(vp_pos)
        visible = self.visible_rows()
        if self._drag_autoscroll_dir > 0 and visible:
            candidate = max(candidate, max(visible))
        elif self._drag_autoscroll_dir < 0 and visible:
            candidate = min(candidate, min(visible))
        return candidate

    def _on_range_select_started(
        self,
        row: int,
        modifiers: Qt.KeyboardModifier,
        global_pos: QPoint,
    ) -> None:
        has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        self._range_select_active = True
        self._range_select_anchor = self._resolve_anchor_index(row) if has_shift else row
        self._range_select_modifiers = modifiers
        self._range_select_cursor_global = global_pos
        self._range_select_end_row = row
        self._pending_click_row = None
        self._pending_click_modifiers = Qt.KeyboardModifier.NoModifier
        self._apply_range_select_end_row(row)
        self._grab_tracking_mouse()
        self._update_drag_autoscroll(self.viewport().mapFromGlobal(global_pos))

    def _apply_range_select_end_row(self, end_row: int) -> None:
        if self.count() == 0:
            return
        end_row = max(0, min(end_row, self.count() - 1))
        start = min(self._range_select_anchor, end_row)
        end = max(self._range_select_anchor, end_row)
        has_ctrl = bool(self._range_select_modifiers & Qt.KeyboardModifier.ControlModifier)
        self._block_selection_sync = True
        if not has_ctrl:
            self.clearSelection()
        self.setCurrentRow(end_row)
        self._select_index_range(start, end)
        if not has_ctrl:
            self._anchor_index = self._range_select_anchor
        self._block_selection_sync = False
        self._sync_selection_visuals()

    def _update_range_select_from_cursor(self) -> None:
        if not self._range_select_active:
            return
        vp_pos = self.viewport().mapFromGlobal(self._range_select_cursor_global)
        candidate = self._resolve_range_select_end_row(vp_pos)
        if self._drag_autoscroll_dir > 0:
            self._range_select_end_row = max(self._range_select_end_row, candidate)
        elif self._drag_autoscroll_dir < 0:
            self._range_select_end_row = min(self._range_select_end_row, candidate)
        else:
            self._range_select_end_row = candidate
        self._apply_range_select_end_row(self._range_select_end_row)

    def _finish_range_select(self) -> None:
        if not self._range_select_active:
            return
        self._range_select_active = False
        self._drag_autoscroll_dir = 0
        self._drag_autoscroll_timer.stop()
        self._reset_card_press()
        self._release_mouse_if_grabbed()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _begin_rubber_band_press(
        self,
        vp_pos: QPoint,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        self._rubber_band_pending = True
        self._rubber_band_active = False
        self._rubber_band_origin_content = self._viewport_to_content(vp_pos)
        self._rubber_band_current = vp_pos
        self._rubber_band_modifiers = modifiers

    def _on_margin_press_started(
        self,
        modifiers: Qt.KeyboardModifier,
        global_pos: QPoint,
    ) -> None:
        vp_pos = self.viewport().mapFromGlobal(global_pos)
        self._begin_rubber_band_press(vp_pos, modifiers)
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.clear_selection_except_current()
        self._grab_tracking_mouse()

    def _handle_rubber_band_move(self, vp_pos: QPoint) -> None:
        if self._rubber_band_pending:
            if (
                vp_pos - self._viewport_from_content(self._rubber_band_origin_content)
            ).manhattanLength() >= QApplication.startDragDistance():
                self._rubber_band_pending = False
                self._rubber_band_active = True
        if not self._rubber_band_active:
            return
        self._rubber_band_current = vp_pos
        self._update_rubber_band_selection()
        self._update_drag_autoscroll(vp_pos)
        rect = self._rubber_band_viewport_rect()
        if rect is not None:
            self._rubber_band_widget.setGeometry(rect)
            self._rubber_band_widget.show()

    def _viewport_from_content(self, content_pos: QPoint) -> QPoint:
        return QPoint(content_pos.x(), content_pos.y() - self._content_y_scroll())

    def _rubber_band_content_rect(self) -> QRect | None:
        if not self._rubber_band_pending and not self._rubber_band_active:
            return None
        current_content = self._viewport_to_content(self._rubber_band_current)
        return QRect(self._rubber_band_origin_content, current_content).normalized()

    def _rubber_band_viewport_rect(self) -> QRect | None:
        content_rect = self._rubber_band_content_rect()
        if content_rect is None:
            return None
        y_scroll = self._content_y_scroll()
        return content_rect.translated(0, -y_scroll)

    def _rubber_band_rect(self) -> QRect | None:
        if not self._rubber_band_active:
            return None
        return self._rubber_band_viewport_rect()

    def _card_rect_viewport(self, row: int) -> QRect:
        item = self.item(row)
        if item is None:
            return QRect()
        item_rect = self.visualItemRect(item)
        widget = self.itemWidget(item)
        if not isinstance(widget, ThumbnailItemWidget):
            return item_rect
        card = widget._card_rect()
        return QRect(
            item_rect.left() + card.left(),
            item_rect.top() + card.top(),
            card.width(),
            card.height(),
        )

    def _card_rect_content(self, row: int) -> QRect:
        return self._card_rect_viewport(row).translated(0, self._content_y_scroll())

    def _update_rubber_band_selection(self) -> None:
        rect = self._rubber_band_content_rect()
        if rect is None or self.count() == 0:
            return
        has_ctrl = bool(self._rubber_band_modifiers & Qt.KeyboardModifier.ControlModifier)
        self._block_selection_sync = True
        if not has_ctrl:
            self.clearSelection()
        selected_rows: list[int] = []
        for row in range(self.count()):
            if rect.intersects(self._card_rect_content(row)):
                item = self.item(row)
                if item:
                    item.setSelected(True)
                    selected_rows.append(row)
        if selected_rows:
            self.setCurrentRow(max(selected_rows))
            if not has_ctrl:
                self._anchor_index = min(selected_rows)
        self._block_selection_sync = False
        self._sync_selection_visuals()

    def _finish_rubber_band(self) -> None:
        if not self._rubber_band_pending and not self._rubber_band_active:
            return
        self._rubber_band_pending = False
        self._rubber_band_active = False
        self._drag_autoscroll_dir = 0
        self._drag_autoscroll_timer.stop()
        self._rubber_band_widget.hide()
        self._release_mouse_if_grabbed()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _autoscroll_for_viewport_pos(self, vp_pos: QPoint) -> tuple[int, int]:
        """Return scroll (direction, step). Direction is -1, 0, or 1."""
        margin = _RANGE_SELECT_SCROLL_MARGIN
        height = max(1, self.viewport().height())
        if vp_pos.y() < margin:
            depth = margin - vp_pos.y()
            ratio = min(1.0, depth / margin)
            step = _RANGE_SELECT_SCROLL_STEP + int(
                (_RANGE_SELECT_SCROLL_MAX_STEP - _RANGE_SELECT_SCROLL_STEP) * ratio
            )
            return -1, step
        if vp_pos.y() > height - margin:
            depth = vp_pos.y() - (height - margin)
            ratio = min(1.0, depth / margin)
            step = _RANGE_SELECT_SCROLL_STEP + int(
                (_RANGE_SELECT_SCROLL_MAX_STEP - _RANGE_SELECT_SCROLL_STEP) * ratio
            )
            return 1, step
        return 0, _RANGE_SELECT_SCROLL_STEP

    def _update_drag_autoscroll(self, vp_pos: QPoint) -> None:
        self._drag_autoscroll_vp_pos = vp_pos
        direction, step = self._autoscroll_for_viewport_pos(vp_pos)
        self._drag_autoscroll_dir = direction
        self._drag_autoscroll_speed = step
        if direction != 0:
            if not self._drag_autoscroll_timer.isActive():
                self._drag_autoscroll_timer.start()
        else:
            self._drag_autoscroll_timer.stop()

    def _drag_autoscroll_step(self) -> None:
        if self._drag_autoscroll_dir == 0:
            self._drag_autoscroll_timer.stop()
            return
        if (
            not self._range_select_active
            and not self._rubber_band_active
            and not self._page_reorder_drag_active
        ):
            self._drag_autoscroll_timer.stop()
            return
        _, step = self._autoscroll_for_viewport_pos(self._drag_autoscroll_vp_pos)
        self._drag_autoscroll_speed = step
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + self._drag_autoscroll_dir * step)
        if self._range_select_active:
            self._update_range_select_from_cursor()
        if self._rubber_band_active:
            self._update_rubber_band_selection()
            rect = self._rubber_band_viewport_rect()
            if rect is not None:
                self._rubber_band_widget.setGeometry(rect)
        if self._page_reorder_drag_active:
            self._update_page_reorder_drag(self._page_reorder_drag_vp_pos)

    def clear(self) -> None:
        super().clear()
        self._anchor_index = 0

    def _resolve_anchor_index(self, fallback_row: int) -> int:
        if 0 <= self._anchor_index < self.count():
            return self._anchor_index
        current = self.currentRow()
        if 0 <= current < self.count():
            self._anchor_index = current
            return current
        anchor = max(0, min(fallback_row, self.count() - 1)) if self.count() else 0
        self._anchor_index = anchor
        return anchor

    def _select_index_range(self, start: int, end: int) -> None:
        for row in range(start, end + 1):
            item = self.item(row)
            if item:
                item.setSelected(True)

    def _apply_item_click(self, row: int, modifiers: Qt.KeyboardModifier) -> None:
        item = self.item(row)
        if not item:
            return
        self._block_selection_sync = True

        has_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if has_shift:
            anchor = self._resolve_anchor_index(row)
            start = min(anchor, row)
            end = max(anchor, row)
            if not has_ctrl:
                self.clearSelection()
            # Set current before selecting: moving current downward after selecting
            # a higher row would otherwise drop the top end of the range.
            self.setCurrentRow(row)
            self._select_index_range(start, end)
        elif has_ctrl:
            item.setSelected(not item.isSelected())
            self.setCurrentRow(row)
            self._anchor_index = row
        else:
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentRow(row)
            self._anchor_index = row

        self._block_selection_sync = False
        self._sync_selection_visuals()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _sync_selection_visuals(self) -> None:
        if self._block_selection_sync:
            return
        current_row = self.currentRow()
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                widget.set_selected(item.isSelected())
                widget.set_current(row == current_row)

    def _start_page_drag_from_row(self, row: int) -> None:
        self._finish_range_select()
        self._finish_rubber_band()
        indices = self.selected_indices()
        if row not in indices:
            self._block_selection_sync = True
            self.clearSelection()
            item = self.item(row)
            if item:
                item.setSelected(True)
            self.setCurrentRow(row)
            self._anchor_index = row
            self._block_selection_sync = False
            indices = [row]
        self._drag_start_indices = sorted(indices)
        self._sync_selection_visuals()
        self._start_page_drag()

    def _build_drag_pixmap(self, indices: list[int]) -> QPixmap:
        width, height = 128, 96
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        preview_row = indices[0]
        item = self.item(preview_row)
        widget = self.itemWidget(item) if item else None
        if isinstance(widget, ThumbnailItemWidget):
            thumb = widget.pixmap()
            if not thumb.isNull():
                painter.setOpacity(0.72)
                scaled = thumb.scaled(
                    width - 16,
                    height - 28,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (width - scaled.width()) // 2
                y = 4
                painter.drawPixmap(x, y, scaled)

        painter.setOpacity(1.0)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#1a1a1a"))
        label = f"{len(indices)}페이지" if len(indices) > 1 else "1페이지"
        painter.drawText(
            0,
            height - 22,
            width,
            20,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        painter.end()
        return pixmap

    def _start_page_drag(self) -> None:
        indices = self._drag_start_indices
        if not indices:
            return

        mime = QMimeData()
        mime.setData(PAGE_MOVE_MIME, ",".join(str(index) for index in indices).encode())

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag_pixmap = self._build_drag_pixmap(indices)
        drag.setPixmap(drag_pixmap)
        drag.setHotSpot(QPoint(drag_pixmap.width() // 2, drag_pixmap.height() // 2))
        self._page_reorder_drag_active = True
        self._page_reorder_drop_index = indices[0]
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._page_reorder_drag_active = False
            self._drag_autoscroll_dir = 0
            self._drag_autoscroll_timer.stop()
            self._show_drop_indicator(None)

    def set_history_state(self, provider) -> None:
        self._history_state = provider

    def _mouse_tracking_active(self) -> bool:
        return (
            self._card_press_row is not None
            or self._range_select_active
            or self._rubber_band_pending
            or self._rubber_band_active
        )

    def _hit_test_at_viewport(self, vp_pos: QPoint) -> tuple[int | None, str]:
        """Return (row, area) where area is 'card', 'margin', or 'empty'."""
        item = self.itemAt(vp_pos)
        if item is None:
            return None, "empty"
        widget = self.itemWidget(item)
        if not isinstance(widget, ThumbnailItemWidget):
            return self.row(item), "card"
        local = widget.mapFrom(self.viewport(), vp_pos)
        if widget._card_rect().contains(local):
            return self.row(item), "card"
        return self.row(item), "margin"

    def _handle_viewport_mouse_press(self, event: QMouseEvent) -> None:
        global_pos = event.globalPosition().toPoint()
        vp_pos = event.position().toPoint()
        row, area = self._hit_test_at_viewport(vp_pos)
        if area == "card" and row is not None:
            self._on_thumb_pressed(row, event.modifiers(), global_pos)
            return
        if area == "margin":
            self._on_margin_press_started(event.modifiers(), global_pos)
            return
        self._begin_rubber_band_press(vp_pos, event.modifiers())
        self._grab_tracking_mouse()

    def _handle_mouse_move_global(self, global_pos: QPoint) -> None:
        vp_pos = self.viewport().mapFromGlobal(global_pos)

        if self._card_press_row is not None and not self._card_press_drag_started:
            if self._handle_card_press_move(global_pos):
                return

        if self._rubber_band_pending or self._rubber_band_active:
            self._handle_rubber_band_move(vp_pos)
            return

        if self._range_select_active:
            self._range_select_cursor_global = global_pos
            self._update_range_select_from_cursor()
            self._update_drag_autoscroll(
                self.viewport().mapFromGlobal(self._range_select_cursor_global)
            )

    def _handle_mouse_release(self) -> None:
        if self._rubber_band_pending or self._rubber_band_active:
            self._finish_rubber_band()
            return
        if self._range_select_active:
            self._finish_range_select()
            return
        if self._card_press_row is not None and not self._card_press_drag_started:
            self._apply_item_click(self._card_press_row, self._card_press_modifiers)
            self._reset_card_press()
            self._release_mouse_if_grabbed()
            return
        self._reset_card_press()
        self._release_mouse_if_grabbed()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport():
            event_type = event.type()
            if (
                event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._handle_viewport_mouse_press(event)
                return True
            if event_type == QEvent.Type.MouseMove and (
                self._mouse_tracking_active() or self._tracking_mouse_grabbed()
            ):
                self._handle_mouse_move_global(event.globalPosition().toPoint())
                return True
            if (
                event_type == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and (self._mouse_tracking_active() or self._tracking_mouse_grabbed())
            ):
                self._handle_mouse_release()
                return True
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._mouse_tracking_active() or self._tracking_mouse_grabbed():
            self._handle_mouse_move_global(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and (self._mouse_tracking_active() or self._tracking_mouse_grabbed())
        ):
            self._handle_mouse_release()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:
        self._release_mouse_if_grabbed()
        self._reset_card_press()
        self._finish_range_select()
        self._finish_rubber_band()
        super().hideEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Undo):
            self.context_action.emit("undo")
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_Y
        ):
            self.context_action.emit("redo")
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_A
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.select_all_pages()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.clear_all_selection()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.context_action.emit("delete")
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta_y = event.angleDelta().y()
            if delta_y == 0:
                event.accept()
                return
            step = 1 if delta_y > 0 else -1
            new_level = max(1, min(len(THUMB_SCALE_LEVELS), self._thumb_level + step))
            if new_level != self._thumb_level:
                self.set_thumb_level(new_level)
                self.scale_changed.emit(self._thumb_scale)
            event.accept()
            return
        super().wheelEvent(event)

    def _paint_drop_indicator(self, painter: QPainter, y: int, x1: int, x2: int) -> None:
        if x2 <= x1:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(DROP_INDICATOR_COLOR, DROP_INDICATOR_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        tick = DROP_INDICATOR_TICK
        painter.drawLine(x1, y - tick, x1, y + tick)
        painter.drawLine(x2, y - tick, x2, y + tick)
        painter.drawLine(x1, y, x2, y)
        painter.restore()

    def dragMoveEvent(self, event) -> None:
        if not self._mime_is_supported(event.mimeData()):
            super().dragMoveEvent(event)
            return
        pos = self.viewport().mapFrom(self, event.position().toPoint())
        if self._mime_has_page_move(event.mimeData()):
            self._update_page_reorder_drag(pos)
        else:
            self._show_drop_indicator(self._index_at_pos(pos))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        if not self._page_reorder_drag_active:
            self._show_drop_indicator(None)
        super().dragLeaveEvent(event)

    def viewportEvent(self, event: QEvent) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if event_type == QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if event_type == QEvent.Type.DragLeave:
            if not self._page_reorder_drag_active:
                self._show_drop_indicator(None)
            return False
        if event_type == QEvent.Type.Drop:
            return self._handle_drop(event)
        return super().viewportEvent(event)

    def _handle_drag_enter(self, event) -> bool:
        if not self._mime_is_supported(event.mimeData()):
            event.ignore()
            return False
        event.acceptProposedAction()
        return True

    def _handle_drag_move(self, event) -> bool:
        if not self._mime_is_supported(event.mimeData()):
            event.ignore()
            return False
        pos = event.position().toPoint()
        if self._mime_has_page_move(event.mimeData()):
            self._update_page_reorder_drag(pos)
        else:
            self._show_drop_indicator(self._index_at_pos(pos))
        event.acceptProposedAction()
        return True

    def _handle_drop(self, event) -> bool:
        self._show_drop_indicator(None)

        mime = event.mimeData()
        pos = event.position().toPoint()

        if self._mime_has_page_move(mime):
            indices = self._indices_from_page_move_mime(mime)
            index = self._drop_index_at_pos(pos)
            if not indices:
                event.ignore()
                return False
            index = self._adjusted_move_target(index, indices)
            self.pages_move_requested.emit(index, indices)
            event.acceptProposedAction()
            return True

        index = self._index_at_pos(pos)
        paths = self._paths_from_mime(mime)
        if not paths:
            event.ignore()
            return False

        self.drop_at_index.emit(index, paths)
        event.acceptProposedAction()
        return True

    @staticmethod
    def _mime_is_supported(mime) -> bool:
        return (
            ThumbnailListWidget._mime_has_supported_files(mime)
            or ThumbnailListWidget._mime_has_page_move(mime)
        )

    @staticmethod
    def _mime_has_page_move(mime) -> bool:
        return mime.hasFormat(PAGE_MOVE_MIME)

    @staticmethod
    def _indices_from_page_move_mime(mime) -> list[int]:
        if not mime.hasFormat(PAGE_MOVE_MIME):
            return []
        raw = bytes(mime.data(PAGE_MOVE_MIME)).decode("utf-8").strip()
        if not raw:
            return []
        return [int(part) for part in raw.split(",") if part.strip().isdigit()]

    @staticmethod
    def _mime_has_supported_files(mime) -> bool:
        return bool(ThumbnailListWidget._paths_from_mime(mime))

    @staticmethod
    def _paths_from_mime(mime) -> list[str]:
        paths: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path and PdfDocument.is_supported_file(path):
                        paths.append(path)
        return paths

    def _items_in_reading_order(self) -> list[tuple[int, QRect]]:
        items: list[tuple[int, QRect]] = []
        for row in range(self.count()):
            item = self.item(row)
            if item:
                items.append((row, self.visualItemRect(item)))
        items.sort(key=lambda entry: (entry[1].left(), entry[1].top()))
        return items

    def _index_at_pos(self, pos: QPoint) -> int:
        """Return insertion index between pages (0 = before first page)."""
        if self.count() == 0:
            return 0

        ordered = self._items_in_reading_order()
        for row, rect in ordered:
            if pos.y() < rect.center().y():
                return row
        return self.count()

    def _drop_index_at_pos(self, vp_pos: QPoint) -> int:
        """Insertion index for drag reorder; extends while auto-scrolling off-screen."""
        index = self._index_at_pos(vp_pos)
        if not self._page_reorder_drag_active:
            return index
        visible = self.visible_rows()
        candidate = index
        if self._drag_autoscroll_dir > 0 and visible:
            candidate = max(candidate, max(visible) + 1)
        elif self._drag_autoscroll_dir < 0 and visible:
            candidate = min(candidate, min(visible))
        if self._drag_autoscroll_dir > 0:
            self._page_reorder_drop_index = max(self._page_reorder_drop_index, candidate)
            candidate = self._page_reorder_drop_index
        elif self._drag_autoscroll_dir < 0:
            self._page_reorder_drop_index = min(self._page_reorder_drop_index, candidate)
            candidate = self._page_reorder_drop_index
        else:
            self._page_reorder_drop_index = candidate
        return min(max(0, candidate), self.count())

    def _update_page_reorder_drag(self, vp_pos: QPoint) -> None:
        self._page_reorder_drag_vp_pos = vp_pos
        self._show_drop_indicator(self._drop_index_at_pos(vp_pos))
        self._update_drag_autoscroll(vp_pos)

    @staticmethod
    def _adjusted_move_target(target_index: int, indices: list[int]) -> int:
        """For contiguous moves, ignore drop slots inside the moving block."""
        if not indices:
            return target_index
        selected = sorted(indices)
        if selected != list(range(selected[0], selected[-1] + 1)):
            return target_index
        last = selected[-1]
        if selected[0] < target_index <= last + 1:
            return last + 1
        return target_index

    def _item_rect(self, row: int) -> QRect:
        item = self.item(row)
        if item is None:
            return QRect()
        return self.visualItemRect(item)

    @staticmethod
    def _page_label_bottom(item_rect: QRect) -> int:
        return item_rect.bottom() - _THUMB_MARGIN

    @staticmethod
    def _thumb_top(item_rect: QRect) -> int:
        return item_rect.top() + _THUMB_MARGIN

    def _thumb_horizontal_range(self, item_rect: QRect) -> tuple[int, int]:
        cell_w = ThumbnailItemWidget.cell_size(self._thumb_scale).width()
        x1 = item_rect.left() + (item_rect.width() - cell_w) // 2
        return x1, x1 + cell_w

    def _indicator_geometry(self, index: int) -> tuple[int, int, int]:
        if self.count() == 0:
            center = self.viewport().width() // 2
            half = self._thumb_scale // 2
            return 12, center - half, center + half

        if index <= 0:
            rect = self._item_rect(0)
            x1, x2 = self._thumb_horizontal_range(rect)
            y = max(2, (rect.top() + self._thumb_top(rect)) // 2)
            return y, x1, x2

        if index >= self.count():
            rect = self._item_rect(self.count() - 1)
            x1, x2 = self._thumb_horizontal_range(rect)
            y = self._page_label_bottom(rect) + max(2, self.spacing() // 2)
            return y, x1, x2

        prev_rect = self._item_rect(index - 1)
        next_rect = self._item_rect(index)
        x1, x2 = self._thumb_horizontal_range(next_rect)
        y = (self._page_label_bottom(prev_rect) + self._thumb_top(next_rect)) // 2
        return y, x1, x2

    def _indicator_y(self, index: int) -> int:
        return self._indicator_geometry(index)[0]

    def _show_context_menu(self, pos: QPoint) -> None:
        insert_index = self._index_at_pos(pos)
        self._show_drop_indicator(insert_index)
        self.paste_anchor_changed.emit(insert_index)

        menu = QMenu(self)
        can_undo, can_redo = self._history_state()
        act_undo = menu.addAction(_menu_action_text("되돌리기", QKeySequence.StandardKey.Undo))
        act_undo.setEnabled(can_undo)
        act_undo.triggered.connect(lambda: self.context_action.emit("undo"))
        act_redo = menu.addAction(_menu_action_text("재실행", QKeySequence.StandardKey.Redo))
        act_redo.setEnabled(can_redo)
        act_redo.triggered.connect(lambda: self.context_action.emit("redo"))
        menu.addSeparator()
        act_copy = menu.addAction(_menu_action_text("복사", QKeySequence.StandardKey.Copy))
        act_copy.triggered.connect(lambda: self.context_action.emit("copy"))
        act_cut = menu.addAction(_menu_action_text("잘라내기", QKeySequence.StandardKey.Cut))
        act_cut.triggered.connect(lambda: self.context_action.emit("cut"))
        act_paste = menu.addAction(_menu_action_text("붙여넣기", QKeySequence.StandardKey.Paste))
        act_paste.setEnabled(PageClipboard.has_pages())
        act_paste.triggered.connect(lambda: self.paste_at_index.emit(insert_index))
        menu.addAction("이미지로 저장", lambda: self.context_action.emit("export_images"))
        menu.addAction("새 파일로 저장", lambda: self.context_action.emit("export_pdf"))
        menu.addSeparator()
        menu.addAction("페이지 삭제", lambda: self.context_action.emit("delete"))
        menu.addAction("시계 방향 회전", lambda: self.context_action.emit("rotate_cw"))
        menu.addAction("반시계 방향 회전", lambda: self.context_action.emit("rotate_ccw"))
        menu.addSeparator()
        menu.addAction("빈 페이지 삽입", lambda: self.context_action.emit("insert_blank"))
        menu.exec(self.mapToGlobal(pos))

        self._show_drop_indicator(None)


class ThumbnailPanel(QWidget):
    """Left sidebar showing page thumbnails."""

    page_selected = pyqtSignal(int)
    pages_changed = pyqtSignal()
    pages_move_requested = pyqtSignal(int, list)
    insert_requested = pyqtSignal(int, list)
    delete_requested = pyqtSignal(list)
    rotate_requested = pyqtSignal(list, int)
    export_pdf_requested = pyqtSignal(list)
    export_images_requested = pyqtSignal(list)
    blank_page_requested = pyqtSignal(int)
    thumb_scale_changed = pyqtSignal(int)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    copy_pages_requested = pyqtSignal(list)
    cut_pages_requested = pyqtSignal(list)
    paste_pages_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PdfDocument | None = None
        self._thumb_level = DEFAULT_THUMB_SCALE_LEVEL
        self._thumb_scale = thumb_scale_for_level(self._thumb_level)
        self._block_signals = False
        self._pending_rows: set[int] = set()
        self._thumb_cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._loaded_rows: set[int] = set()
        self._paste_anchor_index: int | None = None
        self._refresh_in_progress = False
        self._thumb_load_scheduled = False
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.thumb_stack = QStackedWidget()

        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(8, 8, 8, 8)
        self.empty_hint = QLabel(THUMB_EMPTY_HINT)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: #666666; font-size: 13px;")
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addStretch(1)
        self.thumb_stack.addWidget(empty_page)

        self.list_widget = ThumbnailListWidget()
        self.list_widget.currentRowChanged.connect(self._on_current_changed)
        self.list_widget.drop_at_index.connect(self._on_drop)
        self.list_widget.pages_move_requested.connect(self._on_pages_move)
        self.list_widget.context_action.connect(self._on_context_action)
        self.list_widget.paste_at_index.connect(self.paste_pages_requested.emit)
        self.list_widget.paste_anchor_changed.connect(self._set_paste_anchor)
        self.list_widget.verticalScrollBar().valueChanged.connect(self._on_thumbnail_scroll)
        self.list_widget.scale_changed.connect(self._on_list_scale_changed)
        self.thumb_stack.addWidget(self.list_widget)
        layout.addWidget(self.thumb_stack)

        self.list_widget.set_thumb_level(self._thumb_level)

    def current_thumb_level(self) -> int:
        return self._thumb_level

    def set_thumb_level(self, level: int) -> None:
        level = max(1, min(len(THUMB_SCALE_LEVELS), level))
        if level == self._thumb_level:
            return
        self._thumb_level = level
        self.set_thumbnail_scale(thumb_scale_for_level(level))
        self.thumb_scale_changed.emit(self._thumb_scale)

    def step_thumb_level(self, step: int) -> bool:
        new_level = max(1, min(len(THUMB_SCALE_LEVELS), self._thumb_level + step))
        if new_level == self._thumb_level:
            return False
        self.set_thumb_level(new_level)
        return True

    def _update_empty_state(self) -> None:
        has_pages = bool(self._document and self._document.page_count > 0)
        self.thumb_stack.setCurrentIndex(1 if has_pages else 0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if ThumbnailListWidget._mime_is_supported(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if ThumbnailListWidget._mime_is_supported(event.mimeData()):
            vp_pos = self.list_widget.viewport().mapFrom(
                self, event.position().toPoint()
            )
            if ThumbnailListWidget._mime_has_page_move(event.mimeData()):
                self.list_widget._update_page_reorder_drag(vp_pos)
            else:
                self.list_widget._show_drop_indicator(
                    self.list_widget._index_at_pos(vp_pos)
                )
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = ThumbnailListWidget._paths_from_mime(event.mimeData())
        if not paths:
            event.ignore()
            return
        mapped = self.list_widget.mapFrom(self, event.position().toPoint())
        index = self.list_widget._index_at_pos(mapped)
        self.list_widget._show_drop_indicator(None)
        self.insert_requested.emit(index, paths)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.list_widget._show_drop_indicator(None)
        super().dragLeaveEvent(event)

    def set_document(self, document: PdfDocument | None) -> None:
        self._document = document
        self.list_widget.set_history_state(self._history_state)
        self.refresh()

    def _history_state(self) -> tuple[bool, bool]:
        if self._document is None:
            return False, False
        return self._document.can_undo(), self._document.can_redo()

    def refresh(self, keep_index: int | None = None, select_indices: list[int] | None = None) -> None:
        self._refresh_in_progress = True
        self._thumb_load_scheduled = False
        self._block_signals = True
        self._clear_thumbnail_cache()
        self._pending_rows.clear()
        if select_indices:
            keep_index = select_indices[0]
        lw = self.list_widget
        lw.setUpdatesEnabled(False)
        lw.clear()
        if self._document and self._document.page_count > 0:
            placeholder = self._placeholder_pixmap()
            for index in range(self._document.page_count):
                item = QListWidgetItem()
                item.setData(THUMB_ROLE, index)
                lw.addItem(item)
                lw.set_item_widget(index, placeholder, index + 1)
                self._pending_rows.add(index)

            target = keep_index if keep_index is not None else 0
            target = max(0, min(target, lw.count() - 1))
            if select_indices:
                lw._block_selection_sync = True
                for row in select_indices:
                    if 0 <= row < lw.count():
                        lw.item(row).setSelected(True)
                lw._block_selection_sync = False
                target = max(0, min(select_indices[0], lw.count() - 1))
            lw._set_focus_row(target)
            lw._sync_selection_visuals()
            lw.scroll_to_row(target)
        lw.setUpdatesEnabled(True)
        self._block_signals = False
        self._refresh_in_progress = False
        self._update_empty_state()
        if self._document and self._document.page_count > 0:
            QTimer.singleShot(0, lw._sync_item_widget_geometry)
            self._schedule_thumbnail_load()

    def invalidate_thumbnails(self, rows: list[int]) -> None:
        for row in rows:
            self._thumb_cache.pop(row, None)
            self._loaded_rows.discard(row)
            if 0 <= row < self.list_widget.count():
                self._pending_rows.add(row)
                self._set_row_placeholder(row)
        self._schedule_thumbnail_load()

    def remove_pages(
        self,
        indices: list[int],
        keep_index: int | None = None,
        select_indices: list[int] | None = None,
    ) -> None:
        if not self._document:
            return

        deleted = sorted({index for index in indices if 0 <= index < self.list_widget.count()})
        if not deleted:
            return

        self._block_signals = True
        self._clear_thumbnail_cache()
        for row in reversed(deleted):
            item = self.list_widget.takeItem(row)
            del item

        self._renumber_page_labels()
        count = self.list_widget.count()
        if count == 0:
            self._pending_rows.clear()
            self._block_signals = False
            self._update_empty_state()
            return

        target = 0 if keep_index is None else max(0, min(keep_index, count - 1))
        if select_indices:
            self.list_widget._block_selection_sync = True
            self.list_widget.clearSelection()
            for row in select_indices:
                if 0 <= row < count:
                    self.list_widget.item(row).setSelected(True)
            target = max(0, min(select_indices[0], count - 1))
            self.list_widget._block_selection_sync = False
        self.list_widget._set_focus_row(target)
        self.list_widget._sync_selection_visuals()
        self.list_widget.scroll_to_row(target)

        first_changed = min(deleted[0], count - 1)
        for row in range(first_changed, count):
            self._pending_rows.add(row)
            self._set_row_placeholder(row)

        self._block_signals = False
        self._schedule_thumbnail_load()

    def insert_pages_at(
        self,
        index: int,
        count: int,
        keep_index: int | None = None,
        select_indices: list[int] | None = None,
    ) -> None:
        if count <= 0 or not self._document:
            return

        index = max(0, min(index, self.list_widget.count()))
        self._block_signals = True
        self._clear_thumbnail_cache()
        placeholder = self._placeholder_pixmap()
        for offset in range(count):
            row = index + offset
            item = QListWidgetItem()
            item.setData(THUMB_ROLE, row)
            self.list_widget.insertItem(row, item)
            self.list_widget.set_item_widget(row, placeholder, row + 1)
            self._pending_rows.add(row)

        self._renumber_page_labels()

        for row in range(index, self.list_widget.count()):
            self._pending_rows.add(row)
            self._set_row_placeholder(row)

        target = index if keep_index is None else max(0, min(keep_index, self.list_widget.count() - 1))
        if select_indices:
            self.list_widget._block_selection_sync = True
            self.list_widget.clearSelection()
            for row in select_indices:
                if 0 <= row < self.list_widget.count():
                    self.list_widget.item(row).setSelected(True)
            target = max(0, min(select_indices[0], self.list_widget.count() - 1))
            self.list_widget._block_selection_sync = False
        self.list_widget._set_focus_row(target)
        self.list_widget._sync_selection_visuals()
        self.list_widget.scroll_to_row(target)
        self._block_signals = False
        self._update_empty_state()
        QTimer.singleShot(0, self.list_widget._sync_item_widget_geometry)
        self._schedule_thumbnail_load()

    def _placeholder_pixmap(self) -> QPixmap:
        thumb_w = max(32, self._thumb_scale)
        thumb_h = max(45, int(thumb_w * 1.4))
        pixmap = QPixmap(thumb_w, thumb_h)
        pixmap.fill(QColor("#f0f0f0"))
        return pixmap

    def _set_row_placeholder(self, row: int) -> None:
        item = self.list_widget.item(row)
        widget = self.list_widget.itemWidget(item)
        if item and isinstance(widget, ThumbnailItemWidget):
            widget.set_pixmap(self._placeholder_pixmap())
            size = widget.sizeHint()
            widget.setFixedSize(size)
            item.setSizeHint(size)

    def _renumber_page_labels(self) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                widget.set_list_row(row)
                widget.set_page_number(row + 1)
                item.setData(THUMB_ROLE, row)

    def _render_thumbnail(self, index: int) -> QPixmap:
        assert self._document is not None
        if self._document.rendering_paused:
            return self._placeholder_pixmap()
        pix = self._document.render_thumbnail_pixmap(index, self._thumb_scale)
        return pixmap_from_fitz(pix)

    def _clear_thumbnail_cache(self) -> None:
        self._thumb_cache.clear()
        self._loaded_rows.clear()

    def _cache_get(self, row: int) -> QPixmap | None:
        pixmap = self._thumb_cache.pop(row, None)
        if pixmap is None:
            return None
        self._thumb_cache[row] = pixmap
        return pixmap

    def _cache_put(self, row: int, pixmap: QPixmap) -> None:
        self._thumb_cache.pop(row, None)
        self._thumb_cache[row] = pixmap
        while len(self._thumb_cache) > THUMB_CACHE_MAX:
            keep = self._rows_to_keep_loaded()
            evicted_row = next((cached for cached in self._thumb_cache if cached not in keep), None)
            if evicted_row is None:
                evicted_row, _ = self._thumb_cache.popitem(last=False)
            else:
                del self._thumb_cache[evicted_row]
            self._evict_row_thumbnail(evicted_row)

    def _rows_to_keep_loaded(self) -> set[int]:
        keep = set(self.list_widget.visible_rows())
        current = self.list_widget.currentRow()
        if current >= 0:
            keep.update(
                range(
                    max(0, current - THUMB_KEEP_BUFFER),
                    min(self.list_widget.count(), current + THUMB_KEEP_BUFFER + 1),
                )
            )
        keep.update(self.selected_indices())
        return keep

    def _evict_row_thumbnail(self, row: int) -> None:
        self._loaded_rows.discard(row)
        if 0 <= row < self.list_widget.count():
            self._set_row_placeholder(row)
            self._pending_rows.add(row)

    def _release_offscreen_thumbnails(self) -> None:
        keep = self._rows_to_keep_loaded()
        for row in list(self._thumb_cache.keys()):
            if row in keep:
                continue
            del self._thumb_cache[row]
            if row in self._loaded_rows:
                self._evict_row_thumbnail(row)

    def selected_indices(self) -> list[int]:
        lw = self.list_widget
        return sorted(lw.row(item) for item in lw.selectedItems())

    def current_index(self) -> int:
        if self.list_widget.count() == 0:
            return 0
        return max(0, self.list_widget.currentRow())

    def set_current_index(self, index: int) -> None:
        if 0 <= index < self.list_widget.count():
            self.list_widget._set_focus_row(index)
            self.list_widget.scroll_to_row(index)
            self.list_widget._sync_selection_visuals()

    def _on_list_scale_changed(self, scale: int) -> None:
        self.set_thumbnail_scale(scale)
        self.thumb_scale_changed.emit(scale)

    def set_thumbnail_scale(self, width: int) -> None:
        self._thumb_level = thumb_level_for_scale(width)
        self._thumb_scale = thumb_scale_for_level(self._thumb_level)
        self.list_widget.set_thumb_level(self._thumb_level)
        self.list_widget.set_thumbnail_size(self._thumb_scale)
        if not self._document or self.list_widget.count() == 0:
            return

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                widget.set_thumb_scale(self._thumb_scale)
                size = widget.sizeHint()
                widget.setFixedSize(size)
                item.setSizeHint(size)

        self.list_widget._sync_item_widget_geometry()
        self._clear_thumbnail_cache()
        self._apply_fast_scale_preview()
        self._pending_rows = set(range(self.list_widget.count()))
        self._schedule_thumbnail_load()

    def _apply_fast_scale_preview(self) -> None:
        """Instantly rescale existing pixmaps so layout updates feel immediate."""
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if not item or not isinstance(widget, ThumbnailItemWidget):
                continue
            current = widget.pixmap()
            if current.isNull():
                continue
            widget.set_pixmap(current)
            size = widget.sizeHint()
            widget.setFixedSize(size)
            item.setSizeHint(size)

        self.list_widget.doItemsLayout()

    def _on_thumbnail_scroll(self, _value: int) -> None:
        if self._refresh_in_progress:
            return
        self._release_offscreen_thumbnails()
        if self._pending_rows:
            self._schedule_thumbnail_load()

    def _schedule_thumbnail_load(self) -> None:
        if self._thumb_load_scheduled or not self._pending_rows:
            return
        self._thumb_load_scheduled = True
        QTimer.singleShot(0, self._run_scheduled_thumbnail_load)

    def _run_scheduled_thumbnail_load(self) -> None:
        self._thumb_load_scheduled = False
        self._process_pending_thumbnails()

    def _process_pending_thumbnails(self, batch_size: int = 4) -> None:
        if not self._document or not self._pending_rows:
            return
        if self._document.rendering_paused:
            return

        visible_pending = [
            row for row in self.list_widget.visible_rows() if row in self._pending_rows
        ]
        if not visible_pending:
            current = self.list_widget.currentRow()
            if current >= 0 and current in self._pending_rows:
                visible_pending = [current]
            else:
                self._release_offscreen_thumbnails()
                return

        for row in visible_pending[:batch_size]:
            self._update_thumbnail_row(row)
            self._pending_rows.discard(row)

        self._release_offscreen_thumbnails()

        if any(row in self._pending_rows for row in self.list_widget.visible_rows()):
            self._schedule_thumbnail_load()
        elif self._pending_rows:
            current = self.list_widget.currentRow()
            nearby = [
                row
                for row in range(
                    max(0, current - 2),
                    min(self.list_widget.count(), current + 3),
                )
                if row in self._pending_rows
            ]
            if nearby:
                for row in nearby[:batch_size]:
                    self._update_thumbnail_row(row)
                    self._pending_rows.discard(row)
                self._release_offscreen_thumbnails()
                if self._pending_rows:
                    self._schedule_thumbnail_load()

    def _update_thumbnail_row(self, row: int) -> None:
        pixmap = self._cache_get(row)
        if pixmap is None or pixmap.isNull():
            pixmap = self._render_thumbnail(row)
            self._cache_put(row, pixmap)
        self.list_widget.update_item_pixmap(row, pixmap)
        self._loaded_rows.add(row)

    def get_panel_width_range(self) -> tuple[int, int, int]:
        """Return fixed width for single-column thumbnail sidebar."""
        col = ThumbnailListWidget.column_width_for(self._thumb_scale)
        fixed_w = max(_PANEL_HEADER_MIN_WIDTH, col)
        return fixed_w, fixed_w, fixed_w

    def get_width_limits(self) -> tuple[int, int]:
        """Backward-compatible helper returning (default, max)."""
        _, default_w, max_w = self.get_panel_width_range()
        return default_w, max_w

    def _set_paste_anchor(self, index: int) -> None:
        self._paste_anchor_index = max(0, index)

    def resolve_paste_index(self, menu_pos: QPoint | None = None) -> int:
        lw = self.list_widget
        if lw.count() == 0:
            return 0
        if menu_pos is not None:
            return lw._index_at_pos(menu_pos)
        if self._paste_anchor_index is not None:
            return min(self._paste_anchor_index, lw.count())
        selected = self.selected_indices()
        if selected:
            return max(selected) + 1
        row = lw.currentRow()
        if row >= 0:
            return row + 1
        return lw.count()

    def copy_indices(self) -> list[int]:
        indices = self.selected_indices()
        if indices:
            return indices
        row = self.current_index()
        if row >= 0:
            return [row]
        return []

    def _on_current_changed(self, row: int) -> None:
        if self._block_signals or row < 0:
            return
        self._paste_anchor_index = row + 1
        self.page_selected.emit(row)

    def _on_drop(self, index: int, paths: list[str]) -> None:
        self._set_paste_anchor(index)
        self.insert_requested.emit(index, paths)

    def _on_pages_move(self, target_index: int, indices: list[int]) -> None:
        self._set_paste_anchor(target_index)
        self.pages_move_requested.emit(target_index, indices)

    def _on_context_action(self, action: str) -> None:
        indices = self.selected_indices()
        if action == "undo":
            self.undo_requested.emit()
            return
        if action == "redo":
            self.redo_requested.emit()
            return
        if action == "copy":
            copy_indices = self.copy_indices()
            if copy_indices:
                self.copy_pages_requested.emit(copy_indices)
            return
        if action == "cut":
            cut_indices = self.copy_indices()
            if cut_indices:
                self.cut_pages_requested.emit(cut_indices)
            return
        if action == "delete":
            self.delete_requested.emit(indices)
        elif action == "insert":
            self.insert_requested.emit(self._insert_index_after_current(), [])
        elif action == "replace":
            self.insert_requested.emit(self.current_index(), [])
        elif action == "export_pdf":
            self.export_pdf_requested.emit(indices or [self.current_index()])
        elif action == "rotate_cw":
            self.rotate_requested.emit(indices or [self.current_index()], 90)
        elif action == "rotate_ccw":
            self.rotate_requested.emit(indices or [self.current_index()], -90)
        elif action == "insert_blank":
            self.blank_page_requested.emit(self._insert_index_after_current())
        elif action == "export_images":
            self.export_images_requested.emit(indices or [self.current_index()])

    def _insert_index_after_current(self) -> int:
        if self.list_widget.count() == 0:
            return 0
        return self.current_index() + 1
