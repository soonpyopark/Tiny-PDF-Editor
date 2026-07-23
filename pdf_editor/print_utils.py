"""Render PDF pages to a Qt printer / on-screen print preview."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QApplication

from pdf_editor.document import PdfDocument
from pdf_editor.pixmap_utils import pixmap_from_fitz

# Preview stays light so large documents do not exhaust RAM.
_PREVIEW_MAX_DPI = 120
_PREVIEW_MAX_EDGE_PX = 1200


def _iter_print_page_indices(printer: QPrinter, page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    if printer.printRange() == QPrinter.PrintRange.PageRange:
        first = max(1, printer.fromPage())
        last = min(page_count, printer.toPage())
        if first > last:
            return []
        return list(range(first - 1, last))
    return list(range(page_count))


def render_preview_page(
    document: PdfDocument,
    page_index: int,
    *,
    max_edge_px: int = _PREVIEW_MAX_EDGE_PX,
    max_dpi: float = _PREVIEW_MAX_DPI,
) -> QPixmap:
    """Render one page for on-screen print preview (low DPI, single page)."""
    if page_index < 0 or page_index >= document.page_count:
        return QPixmap()

    page_rect = document.get_page_rect(page_index)
    if page_rect.width <= 0 or page_rect.height <= 0:
        return QPixmap()

    zoom_dpi = max_dpi / 72.0
    zoom_edge = max_edge_px / max(page_rect.width, page_rect.height)
    zoom = min(zoom_dpi, zoom_edge)
    pix = document.render_page_pixmap(page_index, zoom)
    return pixmap_from_fitz(pix)


def print_document(
    document: PdfDocument,
    printer: QPrinter,
    *,
    progress: Callable[[int, int], bool] | None = None,
    max_dpi: float | None = None,
) -> None:
    """Print document pages using the settings chosen in QPrintDialog.

    ``progress(current_1based, total)`` may return False to cancel.
    Between pages the UI event loop is pumped so the app stays responsive.
    """
    page_indices = _iter_print_page_indices(printer, document.page_count)
    if not page_indices:
        return

    painter = QPainter(printer)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    try:
        target = printer.pageRect(QPrinter.Unit.DevicePixel)
        dpi = float(max(72, printer.resolution()))
        if max_dpi is not None:
            dpi = min(dpi, max_dpi)

        total = len(page_indices)
        for job_index, page_index in enumerate(page_indices):
            if progress is not None and not progress(job_index + 1, total):
                break
            if job_index > 0:
                printer.newPage()

            page_rect = document.get_page_rect(page_index)
            if page_rect.width <= 0 or page_rect.height <= 0:
                continue

            render_zoom = dpi / 72.0
            page_pixel_w = page_rect.width * render_zoom
            page_pixel_h = page_rect.height * render_zoom
            fit = min(
                target.width() / page_pixel_w,
                target.height() / page_pixel_h,
                1.0,
            )
            zoom = render_zoom * fit

            pix = document.render_page_pixmap(page_index, zoom)
            qpix = pixmap_from_fitz(pix)

            x = target.x() + (target.width() - qpix.width()) // 2
            y = target.y() + (target.height() - qpix.height()) // 2
            painter.drawPixmap(int(x), int(y), qpix)

            # Keep UI alive on long jobs; drop pixmap refs early.
            del pix
            del qpix
            QApplication.processEvents()
    finally:
        if painter.isActive():
            painter.end()
