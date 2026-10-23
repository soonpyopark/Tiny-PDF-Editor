"""Regression tests for signature stamp place / move / delete on rotated pages.

Run:
  .\\.venv\\Scripts\\python.exe -m unittest tests.test_signature_stamp_rotation -v
"""

from __future__ import annotations

import sys
import unittest

import pymupdf as fitz
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from pdf_editor.document import PdfDocument
from pdf_editor.page_viewer import PageViewer
from pdf_editor.signature_stamp import prepare_signature_from_qimage

_APP: QApplication | None = None


def _ensure_app() -> QApplication:
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication(sys.argv)
        return _APP
    return app  # type: ignore[return-value]


def _l_signature_png() -> tuple[bytes, int, int]:
    """Black L on transparent — orientation is unambiguous after rasterize."""
    image = QImage(120, 80, QImage.Format.Format_RGBA8888)
    image.fill(QColor(255, 255, 255, 0))
    painter = QPainter(image)
    painter.fillRect(10, 10, 20, 60, QColor(0, 0, 0))
    painter.fillRect(10, 50, 90, 20, QColor(0, 0, 0))
    painter.end()
    prepared = prepare_signature_from_qimage(image)
    assert prepared is not None
    return prepared.png_bytes, prepared.width, prepared.height


def _ink_centroid(pix: fitz.Pixmap, rect: fitz.Rect) -> tuple[float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    x0, y0 = int(rect.x0), int(rect.y0)
    x1, y1 = int(rect.x1), int(rect.y1)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not (0 <= x < pix.width and 0 <= y < pix.height):
                continue
            if pix.pixel(x, y)[0] < 40:
                xs.append(float(x))
                ys.append(float(y))
    if not xs:
        return None
    return (
        (sum(xs) / len(xs) - rect.x0) / max(rect.width, 1.0),
        (sum(ys) / len(ys) - rect.y0) / max(rect.height, 1.0),
    )


def _dark_count(pix: fitz.Pixmap, rect: fitz.Rect, *, threshold: int = 40) -> int:
    count = 0
    for y in range(int(rect.y0), int(rect.y1)):
        for x in range(int(rect.x0), int(rect.x1)):
            if 0 <= x < pix.width and 0 <= y < pix.height and pix.pixel(x, y)[0] < threshold:
                count += 1
    return count


def _rotated_blank_doc(page_rotation: int) -> PdfDocument:
    """Portrait mediabox + /Rotate, matching common landscape export PDFs."""
    document = PdfDocument()
    document._doc.new_page(width=595, height=842)
    if page_rotation:
        document._doc[0].set_rotation(page_rotation)
    return document


def _stamp_dest(page: fitz.Page) -> fitz.Rect:
    rect = page.rect
    return fitz.Rect(
        rect.width * 0.68,
        rect.height * 0.52,
        rect.width * 0.68 + 120,
        rect.height * 0.52 + 80,
    )


class SignatureStampRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ensure_app()
        cls.png_bytes, cls.img_w, cls.img_h = _l_signature_png()

    def test_place_orientation_matches_preview_for_each_rotation(self) -> None:
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                document = _rotated_blank_doc(rotation)
                dest = _stamp_dest(document._doc[0])
                if rotation == 0:
                    # Unrotated A4 portrait: use a dest that fits.
                    dest = fitz.Rect(400, 700, 520, 780)
                    baseline_doc = fitz.open()
                    baseline_page = baseline_doc.new_page(width=595, height=842)
                    baseline_page.insert_image(
                        dest, stream=self.png_bytes, keep_proportion=False
                    )
                    baseline = _ink_centroid(baseline_page.get_pixmap(alpha=False), dest)
                    baseline_doc.close()
                else:
                    size = document.get_page_rect(0)
                    baseline_doc = fitz.open()
                    baseline_page = baseline_doc.new_page(
                        width=size.width, height=size.height
                    )
                    baseline_page.insert_image(
                        dest, stream=self.png_bytes, keep_proportion=False
                    )
                    baseline = _ink_centroid(baseline_page.get_pixmap(alpha=False), dest)
                    baseline_doc.close()

                document.stamp_image(0, self.png_bytes, dest)
                page = document._doc[0]
                self.assertTrue(document._signature_draw_present(page, dest))
                pix = document.render_page_pixmap(0, 1.0)
                self.assertGreater(_dark_count(pix, dest), 500)
                stamped = _ink_centroid(pix, dest)
                self.assertIsNotNone(stamped)
                self.assertIsNotNone(baseline)
                assert stamped is not None and baseline is not None
                self.assertAlmostEqual(stamped[0], baseline[0], delta=0.05)
                self.assertAlmostEqual(stamped[1], baseline[1], delta=0.05)

    def test_delete_clears_stamp_for_each_rotation(self) -> None:
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                document = _rotated_blank_doc(rotation)
                dest = (
                    fitz.Rect(400, 700, 520, 780)
                    if rotation == 0
                    else _stamp_dest(document._doc[0])
                )
                document.stamp_image(0, self.png_bytes, dest)
                before = _dark_count(document.render_page_pixmap(0, 1.0), dest)
                self.assertGreater(before, 500)
                hit = document.find_signature_stamp_at(
                    0,
                    fitz.Point((dest.x0 + dest.x1) / 2, (dest.y0 + dest.y1) / 2),
                )
                self.assertIsNotNone(hit)
                assert hit is not None
                document.delete_signature_stamp(hit, record_undo=True)
                after = _dark_count(document.render_page_pixmap(0, 1.0), dest)
                self.assertEqual(after, 0)
                self.assertFalse(
                    document._signature_draw_present(document._doc[0], dest)
                )
                self.assertEqual(list(document._iter_page_annots(document._doc[0])), [])

    def test_move_does_not_leave_copy_for_each_rotation(self) -> None:
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                document = _rotated_blank_doc(rotation)
                page_rect = document.get_page_rect(0)
                # Keep old/new far apart so raster checks do not overlap.
                if rotation == 0:
                    old = fitz.Rect(400, 700, 520, 780)
                    new = fitz.Rect(80, 80, 200, 160)
                else:
                    old = fitz.Rect(
                        page_rect.width - 140,
                        page_rect.height - 120,
                        page_rect.width - 20,
                        page_rect.height - 40,
                    )
                    new = fitz.Rect(40, 40, 160, 120)
                self.assertTrue((old & new).is_empty)
                document.stamp_image(0, self.png_bytes, old)
                hit = document.find_signature_stamp_at(
                    0,
                    fitz.Point((old.x0 + old.x1) / 2, (old.y0 + old.y1) / 2),
                )
                self.assertIsNotNone(hit)
                assert hit is not None
                document.replace_signature_stamp(
                    hit, new, self.png_bytes, record_undo=True
                )
                page = document._doc[0]
                self.assertFalse(document._signature_draw_present(page, old))
                self.assertTrue(document._signature_draw_present(page, new))
                pix = document.render_page_pixmap(0, 1.0)
                self.assertEqual(_dark_count(pix, old), 0)
                self.assertGreater(_dark_count(pix, new), 500)
                self.assertEqual(page.read_contents().count(b" Do\n"), 1)

    def test_page_viewer_enter_commit_on_rotated_page(self) -> None:
        document = _rotated_blank_doc(90)
        viewer = PageViewer()
        viewer.resize(1000, 700)
        viewer.show()
        viewer.set_document(document)
        QApplication.processEvents()
        viewer.begin_signature_stamp(self.png_bytes, self.img_w, self.img_h)
        QApplication.processEvents()
        overlay = viewer._stamp_overlay
        self.assertIsNotNone(overlay)
        assert overlay is not None
        rect = overlay.page_rect()
        self.assertTrue(viewer.commit_signature_stamp())
        QApplication.processEvents()
        page = document._doc[0]
        self.assertTrue(document._signature_draw_present(page, rect))
        pix = document.render_page_pixmap(0, 1.0)
        self.assertGreater(_dark_count(pix, rect), 500)
        canvas = viewer._mounted.get(0)
        self.assertIsNotNone(canvas)
        assert canvas is not None
        image = canvas.pixmap().toImage()
        zoom = float(canvas._zoom or 1.0)
        dark = 0
        for y in range(max(0, int(rect.y0 * zoom)), min(image.height(), int(rect.y1 * zoom))):
            for x in range(max(0, int(rect.x0 * zoom)), min(image.width(), int(rect.x1 * zoom))):
                if image.pixelColor(x, y).red() < 40:
                    dark += 1
        self.assertGreater(dark, 200)
        viewer.close()


if __name__ == "__main__":
    unittest.main()
