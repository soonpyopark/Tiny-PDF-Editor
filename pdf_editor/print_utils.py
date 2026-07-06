"""Render PDF pages to a Qt printer."""

from __future__ import annotations

from PyQt6.QtGui import QPainter
from PyQt6.QtPrintSupport import QPrinter

from pdf_editor.document import PdfDocument
from pdf_editor.pixmap_utils import pixmap_from_fitz


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


def print_document(document: PdfDocument, printer: QPrinter) -> None:
    """Print document pages using the settings chosen in QPrintDialog."""
    page_indices = _iter_print_page_indices(printer, document.page_count)
    if not page_indices:
        return

    painter = QPainter(printer)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    try:
        target = printer.pageRect(QPrinter.Unit.DevicePixel)
        dpi = max(72, printer.resolution())

        for job_index, page_index in enumerate(page_indices):
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
    finally:
        if painter.isActive():
            painter.end()
