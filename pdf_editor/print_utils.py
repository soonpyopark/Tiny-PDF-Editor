"""Render PDF pages to a Qt printer / on-screen print preview."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPageLayout, QPen, QPixmap
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


def _fit_scale(page_w: float, page_h: float, target_w: float, target_h: float) -> float:
    """Same fit rule as printing: shrink to fit, never upscale."""
    if page_w <= 0 or page_h <= 0 or target_w <= 0 or target_h <= 0:
        return 1.0
    return min(target_w / page_w, target_h / page_h, 1.0)


def printer_paper_signature(printer: QPrinter) -> str:
    """Cache key for paper size / margins / orientation."""
    layout = printer.pageLayout()
    full = layout.fullRect(QPageLayout.Unit.Point)
    paint = layout.paintRect(QPageLayout.Unit.Point)
    return (
        f"{full.width():.2f}x{full.height():.2f}:"
        f"{paint.x():.2f},{paint.y():.2f},{paint.width():.2f}x{paint.height():.2f}:"
        f"{layout.orientation().value}"
    )


def paper_size_label(printer: QPrinter) -> str:
    """Short human-readable paper description for the preview UI."""
    layout = printer.pageLayout()
    size = layout.pageSize()
    name = size.name() or "용지"
    full = layout.fullRect(QPageLayout.Unit.Millimeter)
    orient = (
        "가로"
        if layout.orientation() == QPageLayout.Orientation.Landscape
        else "세로"
    )
    return f"{name} · {orient} · {full.width():.0f}×{full.height():.0f} mm"


def render_preview_page(
    document: PdfDocument,
    page_index: int,
    *,
    max_edge_px: int = _PREVIEW_MAX_EDGE_PX,
    max_dpi: float = _PREVIEW_MAX_DPI,
) -> QPixmap:
    """Render one PDF page alone (legacy / non-paper preview)."""
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


def render_wysiwyg_preview_page(
    document: PdfDocument,
    page_index: int,
    printer: QPrinter,
    *,
    max_edge_px: int = _PREVIEW_MAX_EDGE_PX,
    max_dpi: float = _PREVIEW_MAX_DPI,
) -> QPixmap:
    """Render one page onto a paper sheet matching *printer* layout (WYSIWYG).

    Uses the same fit-to-printable-area rule as ``print_document``.
    """
    if page_index < 0 or page_index >= document.page_count:
        return QPixmap()

    layout = printer.pageLayout()
    full = layout.fullRect(QPageLayout.Unit.Point)
    paint = layout.paintRect(QPageLayout.Unit.Point)
    if full.width() <= 0 or full.height() <= 0:
        return render_preview_page(
            document,
            page_index,
            max_edge_px=max_edge_px,
            max_dpi=max_dpi,
        )

    page_rect = document.get_page_rect(page_index)
    if page_rect.width <= 0 or page_rect.height <= 0:
        return QPixmap()

    paper_zoom = min(
        max_dpi / 72.0,
        max_edge_px / max(full.width(), full.height()),
    )
    paper_w = max(1, int(round(full.width() * paper_zoom)))
    paper_h = max(1, int(round(full.height() * paper_zoom)))

    # Printable area relative to the full sheet (points → preview pixels).
    paint_x = (paint.x() - full.x()) * paper_zoom
    paint_y = (paint.y() - full.y()) * paper_zoom
    paint_w = max(1.0, paint.width() * paper_zoom)
    paint_h = max(1.0, paint.height() * paper_zoom)

    fit = _fit_scale(
        page_rect.width,
        page_rect.height,
        paint.width(),
        paint.height(),
    )
    content_zoom = paper_zoom * fit
    pix = document.render_page_pixmap(page_index, content_zoom)
    qpix = pixmap_from_fitz(pix)

    canvas = QPixmap(paper_w, paper_h)
    canvas.fill(QColor("#ffffff"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # Subtle printable-area guide (margins).
    painter.setPen(QPen(QColor("#d0d0d0"), 1, Qt.PenStyle.DotLine))
    painter.drawRect(QRectF(paint_x, paint_y, paint_w, paint_h))

    x = int(round(paint_x + (paint_w - qpix.width()) / 2))
    y = int(round(paint_y + (paint_h - qpix.height()) / 2))
    painter.drawPixmap(x, y, qpix)

    painter.setPen(QPen(QColor("#b0b0b0"), 1))
    painter.drawRect(0, 0, paper_w - 1, paper_h - 1)
    painter.end()
    return canvas


def print_document(
    document: PdfDocument,
    printer: QPrinter,
    *,
    progress: Callable[[int, int], bool] | None = None,
    max_dpi: float | None = None,
    page_indices: Sequence[int] | None = None,
) -> None:
    """Print document pages using the settings chosen in QPrintDialog.

    ``progress(current_1based, total)`` may return False to cancel.
    Between pages the UI event loop is pumped so the app stays responsive.
    """
    if page_indices is not None:
        page_indices = [
            int(index)
            for index in page_indices
            if 0 <= int(index) < document.page_count
        ]
    else:
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
            fit = _fit_scale(
                page_pixel_w,
                page_pixel_h,
                float(target.width()),
                float(target.height()),
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
