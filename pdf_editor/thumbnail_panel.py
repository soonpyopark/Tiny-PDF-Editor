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
    QStackedWidget,
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
DROP_INDICATOR_COLOR = QColor("#1a73e8")
DROP_INDICATOR_WIDTH = 2
DROP_INDICATOR_TICK = 7


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

    thumb_pressed = pyqtSignal(object)  # Qt.KeyboardModifiers
    thumb_released = pyqtSignal()
    drag_started = pyqtSignal()

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
        self._press_pos: QPoint | None = None
        self._drag_started = False
        self._selected = False
        self._list_row = 0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet(_CHILD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_THUMB_MARGIN, _THUMB_MARGIN, _THUMB_MARGIN, _THUMB_MARGIN)
        layout.setSpacing(_THUMB_SPACING)

        self._thumb_area = QWidget()
        self._thumb_area.setStyleSheet(_CHILD_STYLE)
        self._thumb_area.setAutoFillBackground(False)
        self._thumb_area.setFixedSize(self._thumb_bounds)
        self._thumb_area.mousePressEvent = self._on_thumb_pressed  # type: ignore[method-assign]
        self._thumb_area.mouseMoveEvent = self._on_thumb_moved  # type: ignore[method-assign]
        self._thumb_area.mouseReleaseEvent = self._on_thumb_released  # type: ignore[method-assign]

        self._image = QLabel(self._thumb_area)
        self._image.setStyleSheet(_CHILD_STYLE)
        self._image.setFrameShape(QFrame.Shape.NoFrame)

        layout.addWidget(self._thumb_area, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._page_label = QLabel(str(page_number))
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._page_label.setFrameShape(QFrame.Shape.NoFrame)
        self._page_label.setFixedHeight(_THUMB_LABEL_HEIGHT)
        self._page_label.setStyleSheet(_CHILD_STYLE)
        self._page_label.mousePressEvent = self._on_label_pressed  # type: ignore[method-assign]
        self._page_label.mouseReleaseEvent = self._on_label_released  # type: ignore[method-assign]
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
        return self.cell_size(self._thumb_scale)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._selected:
            painter.setBrush(QColor("#ebebeb"))
            painter.setPen(QPen(QColor("#8e8e8e"), 1))
        else:
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)
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

    def _on_thumb_pressed(self, event: QMouseEvent) -> None:
        self._handle_item_pressed(event)

    def _on_label_pressed(self, event: QMouseEvent) -> None:
        self._handle_item_pressed(event)

    def _handle_item_pressed(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
            self._drag_started = False
            self.thumb_pressed.emit(event.modifiers())

    def _on_thumb_moved(self, event: QMouseEvent) -> None:
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.pos() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._press_pos = None
            self._drag_started = True
            self.drag_started.emit()

    def _on_thumb_released(self, event: QMouseEvent) -> None:
        self._handle_item_released(event)

    def _on_label_released(self, event: QMouseEvent) -> None:
        self._handle_item_released(event)

    def _handle_item_released(self, event: QMouseEvent) -> None:
        self._press_pos = None
        if event.button() == Qt.MouseButton.LeftButton and not self._drag_started:
            self.thumb_released.emit()
        self._drag_started = False


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
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setStyleSheet(
            """
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
        self._thumb_level = DEFAULT_THUMB_SCALE_LEVEL
        self._thumb_scale = thumb_scale_for_level(self._thumb_level)
        self.configure_grid(self._thumb_scale)
        self.itemSelectionChanged.connect(self._sync_selection_visuals)
        self.currentRowChanged.connect(self._sync_selection_visuals)

    @staticmethod
    def column_width_for(thumb_scale: int) -> int:
        return ThumbnailItemWidget.cell_size(thumb_scale).width() + _PANEL_EDGE_PADDING

    def configure_grid(self, thumb_scale: int) -> None:
        self._thumb_scale = thumb_scale
        self._thumb_level = thumb_level_for_scale(thumb_scale)
        self.setGridSize(ThumbnailItemWidget.list_grid_size(thumb_scale))
        self.setWrapping(False)
        self.setFlow(QListWidget.Flow.TopToBottom)

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
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                size = widget.sizeHint()
                widget.setFixedSize(size)
                item.setSizeHint(size)
        self.doItemsLayout()

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

    def clear(self) -> None:
        super().clear()

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
        widget.thumb_pressed.connect(
            lambda modifiers, w=widget: self._on_thumb_pressed(w.list_row(), modifiers)
        )
        widget.thumb_released.connect(
            lambda w=widget: self._on_thumb_released(w.list_row())
        )
        widget.drag_started.connect(
            lambda w=widget: self._start_page_drag_from_row(w.list_row())
        )
        self.setItemWidget(item, widget)
        size = widget.sizeHint()
        widget.setFixedSize(size)
        item.setSizeHint(size)

    def _on_thumb_pressed(self, row: int, modifiers: Qt.KeyboardModifier) -> None:
        self._pending_click_row = row
        self._pending_click_modifiers = modifiers

    def _on_thumb_released(self, row: int) -> None:
        if self._pending_click_row != row:
            return
        self._apply_item_click(row, self._pending_click_modifiers)
        self._pending_click_row = None
        self._pending_click_modifiers = Qt.KeyboardModifier.NoModifier

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
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                widget.set_selected(item.isSelected())

    def _start_page_drag_from_row(self, row: int) -> None:
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

    def _set_item_widgets_transparent_for_mouse(self, transparent: bool) -> None:
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if widget is not None:
                widget.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                    transparent,
                )

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
        self._set_item_widgets_transparent_for_mouse(True)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._set_item_widgets_transparent_for_mouse(False)
        self._drop_indicator_index = None
        self.update()

    def set_history_state(self, provider) -> None:
        self._history_state = provider

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.itemAt(event.pos()) is None
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self.clear_all_selection()
        super().mousePressEvent(event)

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

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._drop_indicator_index is not None:
            y, x1, x2 = self._indicator_geometry(self._drop_indicator_index)
            self._paint_drop_indicator(painter, y, x1, x2)

    def dragMoveEvent(self, event) -> None:
        if not self._mime_is_supported(event.mimeData()):
            super().dragMoveEvent(event)
            return
        pos = self.viewport().mapFrom(self, event.position().toPoint())
        self._drop_indicator_index = self._index_at_pos(pos)
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop_indicator_index = None
        self.update()
        super().dragLeaveEvent(event)

    def viewportEvent(self, event: QEvent) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if event_type == QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if event_type == QEvent.Type.DragLeave:
            self._drop_indicator_index = None
            self.update()
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
        self._drop_indicator_index = self._index_at_pos(pos)
        self.update()
        event.acceptProposedAction()
        return True

    def _handle_drop(self, event) -> bool:
        self._drop_indicator_index = None
        self.update()

        mime = event.mimeData()
        pos = event.position().toPoint()

        if self._mime_has_page_move(mime):
            indices = self._indices_from_page_move_mime(mime)
            index = self._index_at_pos(pos)
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
        x1 = item_rect.left() + (item_rect.width() - self._thumb_scale) // 2
        return x1, x1 + self._thumb_scale

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
        self._drop_indicator_index = insert_index
        self.paste_anchor_changed.emit(insert_index)
        self.viewport().update()

        menu = QMenu(self)
        can_undo, can_redo = self._history_state()
        act_undo = menu.addAction("되돌리기")
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.setEnabled(can_undo)
        act_undo.triggered.connect(lambda: self.context_action.emit("undo"))
        act_redo = menu.addAction("재실행")
        act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        act_redo.setEnabled(can_redo)
        act_redo.triggered.connect(lambda: self.context_action.emit("redo"))
        menu.addSeparator()
        act_copy = menu.addAction("복사")
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        act_copy.triggered.connect(lambda: self.context_action.emit("copy"))
        act_cut = menu.addAction("잘라내기")
        act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        act_cut.triggered.connect(lambda: self.context_action.emit("cut"))
        act_paste = menu.addAction("붙여넣기")
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)
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

        self._drop_indicator_index = None
        self.viewport().update()


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
            mapped = self.list_widget.mapFrom(self, event.position().toPoint())
            self.list_widget._drop_indicator_index = self.list_widget._index_at_pos(mapped)
            self.list_widget.update()
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
        self.list_widget._drop_indicator_index = None
        self.list_widget.update()
        self.insert_requested.emit(index, paths)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.list_widget._drop_indicator_index = None
        self.list_widget.update()
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
        self._block_signals = True
        self._clear_thumbnail_cache()
        self._pending_rows.clear()
        if select_indices:
            keep_index = select_indices[0]
        self.list_widget.clear()
        if self._document and self._document.page_count > 0:
            placeholder = self._placeholder_pixmap()
            for index in range(self._document.page_count):
                item = QListWidgetItem()
                item.setData(THUMB_ROLE, index)
                self.list_widget.addItem(item)
                self.list_widget.set_item_widget(index, placeholder, index + 1)
                self._pending_rows.add(index)

            target = keep_index if keep_index is not None else 0
            target = max(0, min(target, self.list_widget.count() - 1))
            if select_indices:
                self.list_widget._block_selection_sync = True
                for row in select_indices:
                    if 0 <= row < self.list_widget.count():
                        self.list_widget.item(row).setSelected(True)
                self.list_widget._block_selection_sync = False
                target = max(0, min(select_indices[0], self.list_widget.count() - 1))
            self.list_widget._set_focus_row(target)
            self.list_widget._sync_selection_visuals()
            self.list_widget.scroll_to_row(target)
        self._block_signals = False
        self._update_empty_state()
        QTimer.singleShot(0, self._process_pending_thumbnails)

    def invalidate_thumbnails(self, rows: list[int]) -> None:
        for row in rows:
            self._thumb_cache.pop(row, None)
            self._loaded_rows.discard(row)
            if 0 <= row < self.list_widget.count():
                self._pending_rows.add(row)
                self._set_row_placeholder(row)
        self._process_pending_thumbnails()

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
        self._process_pending_thumbnails()

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
        self._process_pending_thumbnails()

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
        self._process_pending_thumbnails()

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
        self._release_offscreen_thumbnails()
        if self._pending_rows:
            self._process_pending_thumbnails()

    def _process_pending_thumbnails(self, batch_size: int = 6) -> None:
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
            QTimer.singleShot(0, self._process_pending_thumbnails)
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
                    QTimer.singleShot(0, self._process_pending_thumbnails)

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
