"""Thumbnail sidebar with multi-select and drag-and-drop."""

from __future__ import annotations

from collections import OrderedDict

from PyQt6.QtCore import QPoint, QRect, QSize, QEvent, QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
from pdf_editor.pixmap_utils import pixmap_from_fitz

THUMB_ROLE = Qt.ItemDataRole.UserRole + 1
THUMB_EMPTY_HINT = "Drag & Drop here."
DEFAULT_PANEL_WIDTH = 270
THUMB_CACHE_MAX = 50
THUMB_KEEP_BUFFER = 3
PAGE_MOVE_MIME = "application/x-pdf-editor-page-indices"
_CHILD_STYLE = "background: transparent; border: none;"
_THUMB_MARGIN = 6
_THUMB_SPACING = 4
_THUMB_LABEL_HEIGHT = 20
DROP_INDICATOR_COLOR = QColor("#d32f2f")
DROP_INDICATOR_WIDTH = 2
DROP_INDICATOR_TICK = 7


def _paint_checkbox_indicator(painter: QPainter, rect, checked: bool) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if checked:
        painter.setBrush(QColor("#1a73e8"))
        painter.setPen(QPen(QColor("#1a73e8"), 1))
    else:
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#b8b8b8"), 1))
    painter.drawRoundedRect(rect, 3, 3)
    if checked:
        pen = QPen(QColor("#ffffff"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        painter.drawLine(x + 3, y + h // 2, x + w // 2 - 1, y + h - 4)
        painter.drawLine(x + w // 2 - 1, y + h - 4, x + w - 3, y + 3)


class ThumbCheckBox(QCheckBox):
    """Compact checkbox matching Windows-style thumbnail selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        _paint_checkbox_indicator(painter, QRect(1, 1, 16, 16), self.isChecked())
        painter.end()


class ThumbnailItemWidget(QWidget):
    """Single thumbnail with top-left checkbox."""

    check_changed = pyqtSignal(int)
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
        self._block_checkbox = False
        self._press_pos: QPoint | None = None
        self._drag_started = False
        self._selected = False
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
        self._checkbox = ThumbCheckBox(self._thumb_area)
        self._checkbox.move(4, 4)
        self._checkbox.stateChanged.connect(self._on_checkbox_changed)
        self._checkbox.raise_()

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

    @classmethod
    def cell_size(cls, thumb_scale: int) -> QSize:
        thumb_scale = max(32, thumb_scale)
        thumb_h = max(45, int(thumb_scale * 1.4))
        width = thumb_scale + _THUMB_MARGIN * 2
        height = _THUMB_MARGIN * 2 + thumb_h + _THUMB_SPACING + _THUMB_LABEL_HEIGHT
        return QSize(width, height)

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

    def set_checked(self, checked: bool, block_signals: bool = False) -> None:
        self._block_checkbox = block_signals
        self._checkbox.setChecked(checked)
        self._checkbox.update()
        self._block_checkbox = False

    def is_checked(self) -> bool:
        return self._checkbox.isChecked()

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
        self._checkbox.raise_()

    def set_thumb_scale(self, thumb_scale: int) -> None:
        self._thumb_scale = max(32, thumb_scale)
        self._thumb_bounds = QSize(self._thumb_scale, max(45, int(self._thumb_scale * 1.4)))
        self._thumb_area.setFixedSize(self._thumb_bounds)
        current = self.pixmap()
        if not current.isNull():
            self.set_pixmap(current)
        self.updateGeometry()

    def set_page_number(self, page_number: int) -> None:
        self._page_label.setText(str(page_number))

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._checkbox.raise_()
        self._checkbox.update()
        self.update()

    def _on_checkbox_changed(self, state: int) -> None:
        if self._block_checkbox:
            return
        self.check_changed.emit(1 if int(state) else 0)

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
    """List widget with rubber-band multi-select and drop-between insertion."""

    drop_at_index = pyqtSignal(int, list)
    pages_move_requested = pyqtSignal(int, list)
    context_action = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setIconSize(self.iconSize())
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemSelectionChanged.connect(self._sync_checkbox_states)
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
        self._rubber_origin: QPoint | None = None
        self._rubber_rect = QRect()
        self._drop_indicator_index: int | None = None
        self._drag_start_row: int | None = None
        self._block_checkbox_sync = False
        self._pending_thumb_row: int | None = None
        self._pending_thumb_modifiers = Qt.KeyboardModifier.NoModifier
        self._rubber_block_click = False
        self._rubber_additive = False
        self._rubber_press_row = -1
        self._rubber_press_was_selected = False
        self._thumb_scale = 95
        self.configure_grid(self._thumb_scale)
        self.viewport().installEventFilter(self)

    @staticmethod
    def column_width_for(thumb_scale: int) -> int:
        return ThumbnailItemWidget.cell_size(thumb_scale).width() + 16

    def configure_grid(self, thumb_scale: int) -> None:
        self._thumb_scale = thumb_scale
        cell = ThumbnailItemWidget.cell_size(thumb_scale)
        self.setGridSize(cell)
        self.setWrapping(False)
        self.setFlow(QListWidget.Flow.TopToBottom)

    def set_thumbnail_size(self, size: int) -> None:
        self.configure_grid(size)
        self.setIconSize(self.iconSize().__class__(size, int(size * 1.4)))
        self._refresh_item_sizes()

    def _refresh_item_sizes(self) -> None:
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                item.setSizeHint(widget.sizeHint())

    def update_item_pixmap(self, row: int, pixmap: QPixmap) -> None:
        item = self.item(row)
        widget = self.itemWidget(item)
        if item and isinstance(widget, ThumbnailItemWidget):
            widget.set_pixmap(pixmap)
            item.setSizeHint(widget.sizeHint())

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

    def set_item_widget(self, row: int, pixmap: QPixmap, page_number: int) -> None:
        item = self.item(row)
        if not item:
            return

        widget = ThumbnailItemWidget(pixmap, page_number, self._thumb_scale)
        widget.check_changed.connect(lambda checked, r=row: self._on_checkbox_changed(r, checked))
        widget.thumb_pressed.connect(lambda modifiers, r=row: self._on_thumb_pressed(r, modifiers))
        widget.thumb_released.connect(lambda r=row: self._on_thumb_released(r))
        widget.drag_started.connect(lambda r=row: self._start_page_drag_from_row(r))
        widget.installEventFilter(self)
        self.setItemWidget(item, widget)
        item.setSizeHint(widget.sizeHint())

    def _on_checkbox_changed(self, row: int, checked: int) -> None:
        item = self.item(row)
        if not item:
            return
        self._block_checkbox_sync = True
        if checked:
            item.setSelected(True)
            self.setCurrentRow(row)
        else:
            item.setSelected(False)
        widget = self.itemWidget(item)
        if isinstance(widget, ThumbnailItemWidget):
            widget.set_selected(item.isSelected())
        self._block_checkbox_sync = False

    def _on_thumb_pressed(self, row: int, modifiers: Qt.KeyboardModifier) -> None:
        self._pending_thumb_row = row
        self._pending_thumb_modifiers = modifiers

    def _on_thumb_released(self, row: int) -> None:
        if self._rubber_block_click:
            return
        if self._pending_thumb_row != row:
            return
        self._apply_thumb_click(row, self._pending_thumb_modifiers)
        self._pending_thumb_row = None
        self._pending_thumb_modifiers = Qt.KeyboardModifier.NoModifier

    def _row_for_widget(self, widget: QWidget) -> int:
        for row in range(self.count()):
            item = self.item(row)
            if item and self.itemWidget(item) is widget:
                return row
        return -1

    def _event_pos_in_viewport(self, obj: QWidget, event: QMouseEvent) -> QPoint:
        if obj is self.viewport():
            return event.pos()
        return self.viewport().mapFromGlobal(event.globalPosition().toPoint())

    def _begin_rubber_band(
        self,
        pos: QPoint,
        *,
        additive: bool,
        press_row: int = -1,
        was_selected: bool = False,
    ) -> None:
        self._rubber_origin = pos
        self._rubber_rect = QRect(pos, pos)
        self._rubber_block_click = False
        self._rubber_additive = additive
        self._rubber_press_row = press_row
        self._rubber_press_was_selected = was_selected
        if not additive and not (press_row >= 0 and was_selected):
            self._block_checkbox_sync = True
            self.clearSelection()
            self._sync_checkbox_states()
            self._block_checkbox_sync = False

    def _update_rubber_band(self, pos: QPoint) -> bool:
        if self._rubber_origin is None:
            return False
        if (
            pos - self._rubber_origin
        ).manhattanLength() >= QApplication.startDragDistance():
            if (
                self._rubber_press_row >= 0
                and self._rubber_press_was_selected
            ):
                self._rubber_origin = None
                self._rubber_rect = QRect()
                self.viewport().update()
                return False
            self._rubber_block_click = True
        if not self._rubber_block_click:
            return False
        self._rubber_rect = QRect(self._rubber_origin, pos).normalized()
        self._select_in_rubber_band()
        self.viewport().update()
        return True

    def _end_rubber_band(self) -> bool:
        was_rubber = self._rubber_block_click
        if self._rubber_origin is not None:
            self._rubber_origin = None
            self._rubber_rect = QRect()
            self.viewport().update()
        if was_rubber:
            self._sync_checkbox_states()
            self._pending_thumb_row = None
            self._pending_thumb_modifiers = Qt.KeyboardModifier.NoModifier
        self._rubber_block_click = False
        return was_rubber

    def eventFilter(self, obj, event) -> bool:
        if obj is not self.viewport() and not isinstance(obj, ThumbnailItemWidget):
            return super().eventFilter(obj, event)

        event_type = event.type()
        if event_type in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
        ):
            mouse_event = event
            if not isinstance(mouse_event, QMouseEvent):
                return super().eventFilter(obj, event)

            if event_type == QEvent.Type.MouseButtonPress:
                if mouse_event.button() != Qt.MouseButton.LeftButton:
                    return super().eventFilter(obj, event)
                if obj is self.viewport() and self.itemAt(mouse_event.pos()) is not None:
                    return super().eventFilter(obj, event)
                additive = bool(
                    mouse_event.modifiers() & Qt.KeyboardModifier.ControlModifier
                )
                press_row = (
                    self._row_for_widget(obj)
                    if isinstance(obj, ThumbnailItemWidget)
                    else -1
                )
                was_selected = False
                if press_row >= 0:
                    item = self.item(press_row)
                    was_selected = bool(item and item.isSelected())
                self._begin_rubber_band(
                    self._event_pos_in_viewport(obj, mouse_event),
                    additive=additive,
                    press_row=press_row,
                    was_selected=was_selected,
                )
                return False

            if event_type == QEvent.Type.MouseMove:
                if not (mouse_event.buttons() & Qt.MouseButton.LeftButton):
                    return super().eventFilter(obj, event)
                if self._update_rubber_band(
                    self._event_pos_in_viewport(obj, mouse_event)
                ):
                    return isinstance(obj, ThumbnailItemWidget)
                return False

            if event_type == QEvent.Type.MouseButtonRelease:
                if mouse_event.button() != Qt.MouseButton.LeftButton:
                    return super().eventFilter(obj, event)
                if self._end_rubber_band():
                    return isinstance(obj, ThumbnailItemWidget)
                return False

        return super().eventFilter(obj, event)

    def _apply_thumb_click(self, row: int, modifiers: Qt.KeyboardModifier) -> None:
        item = self.item(row)
        if not item:
            return

        self._block_checkbox_sync = True
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            item.setSelected(not item.isSelected())
            self.setCurrentRow(row)
        else:
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentRow(row)
        self._sync_checkbox_states()
        self._block_checkbox_sync = False

    def _sync_checkbox_states(self) -> None:
        if self._block_checkbox_sync:
            return
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                selected = item.isSelected()
                widget.set_checked(selected, block_signals=True)
                widget.set_selected(selected)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._rubber_origin is not None and self._update_rubber_band(event.pos()):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._end_rubber_band()
        super().mouseReleaseEvent(event)

    def _start_page_drag_from_row(self, row: int) -> None:
        self._pending_thumb_row = None
        self._pending_thumb_modifiers = Qt.KeyboardModifier.NoModifier
        if row not in self.selected_indices():
            item = self.item(row)
            if item:
                self._block_checkbox_sync = True
                self.clearSelection()
                item.setSelected(True)
                self.setCurrentRow(row)
                self._sync_checkbox_states()
                self._block_checkbox_sync = False
        self._drag_start_row = row
        self._start_page_drag()

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
        indices = self.selected_indices()
        if not indices and self._drag_start_row is not None:
            indices = [self._drag_start_row]
        if not indices:
            return

        mime = QMimeData()
        mime.setData(PAGE_MOVE_MIME, ",".join(str(index) for index in indices).encode())

        drag = QDrag(self)
        drag.setMimeData(mime)
        self._set_item_widgets_transparent_for_mouse(True)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._set_item_widgets_transparent_for_mouse(False)
        self._drop_indicator_index = None
        self.update()

    def _select_in_rubber_band(self) -> None:
        if not self._rubber_additive:
            self.clearSelection()
        for row in range(self.count()):
            item = self.item(row)
            if not item:
                continue
            rect = self.visualItemRect(item)
            if self._rubber_rect.intersects(rect):
                item.setSelected(True)

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

        if self._rubber_origin is not None and not self._rubber_rect.isNull():
            painter.setPen(QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawRect(self._rubber_rect)

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
        menu = QMenu(self)
        menu.addAction("삭제", lambda: self.context_action.emit("delete"))
        menu.addSeparator()
        menu.addAction("페이지 삽입...", lambda: self.context_action.emit("insert"))
        menu.addAction("페이지 바꾸기...", lambda: self.context_action.emit("replace"))
        menu.addSeparator()
        menu.addAction("페이지보내기...", lambda: self.context_action.emit("export_pdf"))
        menu.addAction("시계 방향 회전", lambda: self.context_action.emit("rotate_cw"))
        menu.addAction("반시계 방향 회전", lambda: self.context_action.emit("rotate_ccw"))
        menu.addSeparator()
        menu.addAction("이미지로보내기...", lambda: self.context_action.emit("export_images"))
        menu.exec(self.mapToGlobal(pos))


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PdfDocument | None = None
        self._thumb_scale = 95
        self._block_signals = False
        self._pending_rows: set[int] = set()
        self._thumb_cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._loaded_rows: set[int] = set()
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
        self.list_widget.verticalScrollBar().valueChanged.connect(self._on_thumbnail_scroll)
        self.thumb_stack.addWidget(self.list_widget)
        layout.addWidget(self.thumb_stack)

        self.list_widget.configure_grid(self._thumb_scale)

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
        self.refresh()

    def refresh(self, keep_index: int | None = None, select_indices: list[int] | None = None) -> None:
        self._block_signals = True
        self._clear_thumbnail_cache()
        self._pending_rows.clear()
        selected = select_indices if select_indices is not None else self.selected_indices()
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
            self.list_widget.setCurrentRow(target)

            for row in selected:
                if 0 <= row < self.list_widget.count():
                    self.list_widget.item(row).setSelected(True)
            self.list_widget._sync_checkbox_states()
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
        self.list_widget.setCurrentRow(target)
        self.list_widget.clearSelection()
        if select_indices is not None:
            for row in select_indices:
                if 0 <= row < count:
                    self.list_widget.item(row).setSelected(True)
        self.list_widget._sync_checkbox_states()

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
        self.list_widget.setCurrentRow(target)
        self.list_widget.clearSelection()
        if select_indices is not None:
            for row in select_indices:
                if 0 <= row < self.list_widget.count():
                    self.list_widget.item(row).setSelected(True)
        self.list_widget._sync_checkbox_states()
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
            item.setSizeHint(widget.sizeHint())

    def _renumber_page_labels(self) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                widget.set_page_number(row + 1)
                item.setData(THUMB_ROLE, row)

    def _render_thumbnail(self, index: int) -> QPixmap:
        assert self._document is not None
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
            self.list_widget.setCurrentRow(index)

    def set_thumbnail_scale(self, width: int) -> None:
        self._thumb_scale = width
        self.list_widget.configure_grid(width)
        self.list_widget.set_thumbnail_size(width)
        if not self._document or self.list_widget.count() == 0:
            return

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if item and isinstance(widget, ThumbnailItemWidget):
                widget.set_thumb_scale(width)
                item.setSizeHint(widget.sizeHint())

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
            item.setSizeHint(widget.sizeHint())

    def _on_thumbnail_scroll(self, _value: int) -> None:
        self._release_offscreen_thumbnails()
        if self._pending_rows:
            self._process_pending_thumbnails()

    def _process_pending_thumbnails(self, batch_size: int = 6) -> None:
        if not self._document or not self._pending_rows:
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
        fixed_w = max(DEFAULT_PANEL_WIDTH, col + 20)
        return fixed_w, fixed_w, fixed_w

    def get_width_limits(self) -> tuple[int, int]:
        """Backward-compatible helper returning (default, max)."""
        _, default_w, max_w = self.get_panel_width_range()
        return default_w, max_w

    def _on_current_changed(self, row: int) -> None:
        if self._block_signals or row < 0:
            return
        self.page_selected.emit(row)

    def _on_drop(self, index: int, paths: list[str]) -> None:
        self.insert_requested.emit(index, paths)

    def _on_pages_move(self, target_index: int, indices: list[int]) -> None:
        self.pages_move_requested.emit(target_index, indices)

    def _on_context_action(self, action: str) -> None:
        indices = self.selected_indices()
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
        elif action == "export_images":
            self.export_images_requested.emit(indices or [self.current_index()])

    def _insert_index_after_current(self) -> int:
        if self.list_widget.count() == 0:
            return 0
        return self.current_index() + 1
