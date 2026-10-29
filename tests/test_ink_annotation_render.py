"""Ink / freehand signatures must appear in the page preview pixmap."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_editor.document import PdfDocument

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "attachments"
    / "PDF____.pdf"
)
_ATTACHMENT = Path(
    r"c:\Users\user\.cursor\projects\d-My-Cursor-Tiny-PDF-Editor"
    r"\attachments\570bdf40-0cb3-4309-97df-f1ae685dfce4\PDF____.pdf"
)


def _dark_pixels(pix: fitz.Pixmap, clip: fitz.Rect, *, threshold: int = 80) -> int:
    x0 = max(0, int(clip.x0))
    y0 = max(0, int(clip.y0))
    x1 = min(pix.width, int(clip.x1))
    y1 = min(pix.height, int(clip.y1))
    if x1 <= x0 or y1 <= y0:
        return 0
    samples = pix.samples
    n = pix.n
    stride = pix.stride
    dark = 0
    for y in range(y0, y1):
        row = y * stride
        for x in range(x0, x1):
            i = row + x * n
            if samples[i] < threshold:
                dark += 1
    return dark


class InkAnnotationRenderTests(unittest.TestCase):
    def test_synthetic_ink_visible_in_preview(self) -> None:
        src = fitz.open()
        page = src.new_page(width=300, height=200)
        annot = page.add_ink_annot(
            [[(40, 40), (80, 120), (120, 50), (160, 130), (200, 60)]]
        )
        annot.set_border(width=3)
        annot.set_colors(stroke=(0, 0, 0))
        annot.update()
        ink_rect = fitz.Rect(annot.rect)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ink.pdf"
            src.save(path)
            src.close()
            document = PdfDocument()
            document.open_file(str(path))
            with_annots = document.render_page_pixmap(0, 2.0, annots=True)
            without = document.render_page_pixmap(0, 2.0, annots=False)
            clip = fitz.Rect(
                ink_rect.x0 * 2,
                ink_rect.y0 * 2,
                ink_rect.x1 * 2,
                ink_rect.y1 * 2,
            )
            self.assertGreater(_dark_pixels(with_annots, clip), 30)
            self.assertEqual(_dark_pixels(without, clip), 0)
            # Default preview path must include annotations.
            default = document.render_page_pixmap(0, 2.0)
            self.assertGreater(_dark_pixels(default, clip), 30)
            document.close()

    def test_fixture_ink_signatures_visible(self) -> None:
        path = _ATTACHMENT if _ATTACHMENT.is_file() else _FIXTURE
        if not path.is_file():
            self.skipTest(f"fixture missing: {path}")
        document = PdfDocument()
        document.open_file(str(path))
        page = document._doc[0]
        inks = [
            annot
            for annot in document._iter_page_annots(page)
            if annot.type and annot.type[0] == fitz.PDF_ANNOT_INK
        ]
        self.assertGreaterEqual(len(inks), 1)
        # Signature block near the bottom of the consent form.
        clip = fitz.Rect(180, 700, 480, 780)
        with_annots = document.render_page_pixmap(0, 1.5, annots=True)
        without = document.render_page_pixmap(0, 1.5, annots=False)
        scaled = fitz.Rect(clip.x0 * 1.5, clip.y0 * 1.5, clip.x1 * 1.5, clip.y1 * 1.5)
        dark_on = _dark_pixels(with_annots, scaled)
        dark_off = _dark_pixels(without, scaled)
        self.assertGreater(dark_on, dark_off + 200)
        document.close()


if __name__ == "__main__":
    unittest.main()
