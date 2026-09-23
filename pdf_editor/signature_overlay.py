"""Floating signature preview with move and resize handles."""

from __future__ import annotations

import pymupdf as fitz
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from pdf_editor.signature_stamp import move_stamp_rect, resize_stamp_rect

HANDLE_SIZE = 8
HANDLE_HIT = 12
HANDLE_CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
}
HANDLE_ORDER = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


class SignatureStampOverlay(QWidget):
    """Transparent PNG preview over a page. Enter or a click elsewhere commits, Esc cancels."""

    commit_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    context_menu_requested = pyqtSignal(object)

    def __init__(
        self,
        host: QWidget,
        canvas: QWidget,
        pixmap: QPixmap,
        page_rect: fitz.Rect,
        image_width: int,
        image_height: int,
        *,
        commit_on_double_click: bool = True,
    ) -> None:
        super().__init__(host)
        self._canvas = canvas
        self._pixmap = pixmap
        self._page_rect = fitz.Rect(page_rect)
        self._image_width = image_width
        self._image_height = image_height
        self._commit_on_double_click = commit_on_double_click
        self._drag_handle: str | None = None
        self._drag_origin = fitz.Rect(page_rect)
        self._drag_page_point: fitz.Point | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        self.sync_geometry()
        self.show()
        self.raise_()
        self.setFocus()

    def canvas(self) -> QWidget | None:
        return self._canvas

    def set_canvas(self, canvas: QWidget | None) -> None:
        self._canvas = canvas
        self.sync_geometry()

    def page_rect(self) -> fitz.Rect:
        return fitz.Rect(self._page_rect)

    def set_page_rect(self, rect: fitz.Rect) -> None:
        self._page_rect = fitz.Rect(rect)
        self.sync_geometry()

    def sync_geometry(self) -> None:
        canvas = self._canvas
        zoom = float(getattr(canvas, "_zoom", 1.0) or 1.0) if canvas is not None else 1.0
        origin = canvas.pos() if canvas is not None else QPoint(0, 0)
        rect = self._page_rect
        self.setGeometry(
            origin.x() + int(round(rect.x0 * zoom)),
            origin.y() + int(round(rect.y0 * zoom)),
            max(8, int(round(rect.width * zoom))),
            max(8, int(round(rect.height * zoom))),
        )
        self.update()

    def _page_point(self, pos: QPoint) -> fitz.Point:
        return self._page_point_from_global(self.mapToGlobal(pos))

    def _page_point_from_global(self, global_pos: QPoint) -> fitz.Point:
        canvas = self._canvas
        zoom = float(getattr(canvas, "_zoom", 1.0) or 1.0) if canvas is not None else 1.0
        if zoom <= 0:
            zoom = 1.0
        if canvas is None:
            return fitz.Point(0, 0)
        mapped = canvas.mapFromGlobal(global_pos)
        return fitz.Point(mapped.x() / zoom, mapped.y() / zoom)

    def _page(self) -> fitz.Rect:
        canvas = self._canvas
        document = getattr(canvas, "_document", None)
        page_index = getattr(canvas, "_page_index", 0)
        if document is not None and 0 <= page_index < document.page_count:
            return document.get_page_rect(page_index)
        return fitz.Rect(self._page_rect)

    def _handle_rects(self) -> dict[str, QRect]:
        w = self.width()
        h = self.height()
        s = HANDLE_SIZE
        cx = (w - s) // 2
        cy = (h - s) // 2
        return {
            "nw": QRect(0, 0, s, s),
            "n": QRect(cx, 0, s, s),
            "ne": QRect(w - s, 0, s, s),
            "e": QRect(w - s, cy, s, s),
            "se": QRect(w - s, h - s, s, s),
            "s": QRect(cx, h - s, s, s),
            "sw": QRect(0, h - s, s, s),
            "w": QRect(0, cy, s, s),
        }

    def _hit_handle(self, pos: QPoint) -> str | None:
        hit = QRect(
            pos.x() - HANDLE_HIT // 2,
            pos.y() - HANDLE_HIT // 2,
            HANDLE_HIT,
            HANDLE_HIT,
        )
        for name in HANDLE_ORDER:
            if self._handle_rects()[name].intersects(hit):
                return name
        return None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(37, 99, 235), 1, Qt.PenStyle.DashLine))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setPen(QPen(QColor(37, 99, 235), 1))
        painter.setBrush(QColor(255, 255, 255))
        for rect in self._handle_rects().values():
            painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_handle = self._hit_handle(event.pos()) or "move"
        self._drag_origin = fitz.Rect(self._page_rect)
        self._drag_page_point = self._page_point_from_global(
            event.globalPosition().toPoint()
        )
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_handle is None:
            handle = self._hit_handle(event.pos())
            if handle is None:
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(QCursor(HANDLE_CURSORS[handle]))
            super().mouseMoveEvent(event)
            return
        point = self._page_point_from_global(event.globalPosition().toPoint())
        page = self._page()
        if self._drag_handle == "move" and self._drag_page_point is not None:
            delta = fitz.Point(
                point.x - self._drag_page_point.x,
                point.y - self._drag_page_point.y,
            )
            self._page_rect = move_stamp_rect(self._drag_origin, delta, page)
        else:
            self._page_rect = resize_stamp_rect(
                self._drag_origin,
                self._drag_handle,
                point,
                self._image_width,
                self._image_height,
                page,
            )
        self.sync_geometry()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.mouseGrabber() == self:
            self.releaseMouse()
        self._drag_handle = None
        self._drag_page_point = None
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.context_menu_requested.emit(event.globalPos())
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Escape,
            Qt.Key.Key_Delete,
            Qt.Key.Key_Backspace,
        ):
            event.ignore()
            return
        super().keyPressEvent(event)
