"""Apply one-pass ONNX OCR as a replaceable invisible text layer."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import fitz
import numpy as np

from pdf_editor.document import PdfDocument
from pdf_editor.ocr_engine import OcrLine, get_ocr_engine
from pdf_editor.ocr_models import models_ready

OCR_ANNOT_TITLE = "tpe:ocr"
OCR_FONTNAME = "tpeocr"
OCR_DPI = 180
SKIP_NATIVE_TEXT_CHARS = 20
_OCR_FONT_TOKEN = b"/tpeocr"
_BT_ET = re.compile(rb"BT\b.*?ET\b", re.DOTALL)
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class OcrRunResult:
    applied: int
    skipped: int
    failed: int
    lines: int


def ocr_ready() -> bool:
    return models_ready()


def _pixmap_rgb(pix) -> np.ndarray:
    samples = np.frombuffer(pix.samples, dtype=np.uint8)
    image = samples.reshape(pix.height, pix.width, pix.n)
    if pix.n >= 3:
        return np.ascontiguousarray(image[:, :, :3])
    return np.repeat(image, 3, axis=2)


def _is_ocr_annot(annot) -> bool:
    try:
        return (annot.info.get("title") or "") == OCR_ANNOT_TITLE
    except Exception:
        return False


def _ocr_boxes(page) -> list[fitz.Rect]:
    return [
        fitz.Rect(annot.rect)
        for annot in PdfDocument._iter_page_annots(page)
        if _is_ocr_annot(annot)
    ]


def _strip_ocr_operators(data: bytes) -> bytes:
    if _OCR_FONT_TOKEN not in data:
        return data
    return _BT_ET.sub(
        lambda match: b"" if _OCR_FONT_TOKEN in match.group(0) else match.group(0),
        data,
    )


def _stream_is_empty(data: bytes) -> bool:
    compact = (
        data.replace(b"\n", b"")
        .replace(b"\r", b"")
        .replace(b" ", b"")
        .replace(b"q", b"")
        .replace(b"Q", b"")
    )
    return not compact


def _set_page_contents(page, xrefs: list[int]) -> None:
    if not xrefs:
        return
    if len(xrefs) == 1:
        page.set_contents(xrefs[0])
        return
    doc = page.parent
    blob = b"\n".join((doc.xref_stream(xref) or b"") for xref in xrefs)
    doc.update_stream(xrefs[0], blob)
    page.set_contents(xrefs[0])


def wipe_ocr_layer(page) -> int:
    """Remove only the previous tpe:ocr text streams. Do not redact."""
    doc = page.parent
    try:
        contents = list(page.get_contents() or [])
    except Exception:
        contents = []
    keep: list[int] = []
    removed = 0
    for xref in contents:
        try:
            data = doc.xref_stream(xref) or b""
        except Exception:
            keep.append(xref)
            continue
        if _OCR_FONT_TOKEN not in data:
            keep.append(xref)
            continue
        stripped = _strip_ocr_operators(data)
        if _stream_is_empty(stripped):
            removed += 1
            continue
        if stripped != data:
            try:
                doc.update_stream(xref, stripped)
            except Exception:
                keep.append(xref)
                continue
            removed += 1
        keep.append(xref)
    if keep and keep != contents:
        try:
            _set_page_contents(page, keep)
        except Exception:
            pass
    annots = [
        annot
        for annot in list(PdfDocument._iter_page_annots(page))
        if _is_ocr_annot(annot)
    ]
    for annot in annots:
        try:
            page.delete_annot(annot)
        except Exception:
            try:
                annot.delete()
            except Exception:
                pass
    return max(removed, len(annots))


def page_has_native_text(page) -> bool:
    ocr_rects = _ocr_boxes(page)
    if not ocr_rects:
        return len((page.get_text("text") or "").strip()) >= SKIP_NATIVE_TEXT_CHARS
    leftover = []
    for word in page.get_text("words") or []:
        rect = fitz.Rect(word[:4])
        text = str(word[4] or "").strip()
        if not text:
            continue
        if any(rect.intersects(box) for box in ocr_rects):
            continue
        leftover.append(text)
    return len("".join(leftover)) >= SKIP_NATIVE_TEXT_CHARS


def _mark_ocr_box(page, box: fitz.Rect) -> None:
    annot = page.add_rect_annot(box)
    annot.set_colors(stroke=None, fill=None)
    annot.set_border(width=0)
    annot.set_opacity(0)
    annot.set_info(title=OCR_ANNOT_TITLE)
    annot.set_flags(2 | 32)
    annot.update()


def _write_ocr_line(page, line: OcrLine, zoom: float) -> bool:
    text = (line.text or "").strip()
    if not text:
        return False
    box = fitz.Rect(
        line.x / zoom,
        line.y / zoom,
        (line.x + line.w) / zoom,
        (line.y + line.h) / zoom,
    )
    if box.is_empty or box.is_infinite:
        return False
    _fontname, fontfile = PdfDocument._resolve_edit_font(text)
    if not fontfile:
        found = PdfDocument._find_installed_cjk_font()
        if found:
            _fontname, fontfile = found
    if PdfDocument._needs_cjk_font(text) and not fontfile:
        return False
    size = max(4.0, min(72.0, float(box.height) * 0.82))
    try:
        font = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font("helv")
        width = float(font.text_length(text, fontsize=size))
        if width > box.width > 1:
            size = max(4.0, size * (box.width / width))
    except Exception:
        pass
    # Fresh font resource name so a previous redact cannot reuse a broken CJK font.
    kwargs: dict[str, object] = {
        "fontsize": size,
        "fontname": OCR_FONTNAME if fontfile else "helv",
        "render_mode": 3,
        "overlay": True,
    }
    if fontfile:
        kwargs["fontfile"] = fontfile
    origin = fitz.Point(box.x0, min(box.y1 - 0.8, box.y0 + size))
    try:
        page.insert_text(origin, text, **kwargs)
    except Exception:
        try:
            page.insert_textbox(box, text, **kwargs)
        except Exception:
            return False
    _mark_ocr_box(page, box)
    return True


def apply_ocr_lines(document: PdfDocument, page_index: int, lines: list[OcrLine], zoom: float) -> int:
    if not (0 <= page_index < len(document._doc)):
        return 0
    page = document._doc[page_index]
    wipe_ocr_layer(page)
    written = 0
    for line in lines:
        if _write_ocr_line(page, line, zoom):
            written += 1
    return written


def run_ocr_on_document(
    document: PdfDocument,
    indices: list[int],
    *,
    skip_native_text: bool = True,
    status_callback: ProgressCallback | None = None,
) -> OcrRunResult:
    if not indices:
        return OcrRunResult(0, 0, 0, 0)
    if status_callback:
        status_callback("OCR을 준비합니다...")
    engine = get_ocr_engine()
    document._record_undo_checkpoint()
    zoom = OCR_DPI / 72.0
    applied = 0
    skipped = 0
    failed = 0
    lines = 0
    total = len(indices)
    for step, page_index in enumerate(indices, start=1):
        if not (0 <= page_index < document.page_count):
            failed += 1
            continue
        if status_callback:
            status_callback(f"OCR 중... {page_index + 1}페이지 ({step}/{total})")
        page = document._doc[page_index]
        if skip_native_text and page_has_native_text(page):
            skipped += 1
            continue
        try:
            pix = document.render_page_pixmap(
                page_index,
                zoom,
                annots=False,
                ignore_pause=True,
            )
            recognized = engine.recognize_page(_pixmap_rgb(pix))
            written = apply_ocr_lines(document, page_index, recognized, zoom)
        except Exception:
            failed += 1
            continue
        if written:
            applied += 1
            lines += written
        else:
            failed += 1
    return OcrRunResult(applied, skipped, failed, lines)
