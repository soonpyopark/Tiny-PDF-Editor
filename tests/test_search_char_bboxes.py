"""Char-bbox search must match visible glyphs (not bad MuPDF search_for hits)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_editor.document import PdfDocument
from pdf_editor.engine import _search_snippet

_SAMPLE = Path(r"D:\Downloads\샘플.pdf")


class SearchCharBBoxTests(unittest.TestCase):
    def test_sample_일반_matches_chrome_count_and_second_hit(self) -> None:
        """샘플.pdf: MuPDF search_for mis-places 2nd 「일반」 onto 사업수행 row."""
        if not _SAMPLE.is_file():
            self.skipTest(f"fixture missing: {_SAMPLE}")
        document = PdfDocument()
        document.open_file(str(_SAMPLE))
        hits = document.search_text("일반")
        # Chrome Find also reports 13 for this file.
        self.assertEqual(len(hits), 13)
        second = hits[1]
        self.assertEqual(second.page_index, 5)
        # Glyph box for 「일반」 inside 「제안업체 일반사항」.
        expected = fitz.Rect(206.16, 221.40, 230.16, 233.41)
        self.assertLess(abs(second.rect.x0 - expected.x0), 1.0)
        self.assertLess(abs(second.rect.y0 - expected.y0), 1.0)
        self.assertLess(abs(second.rect.x1 - expected.x1), 1.0)
        self.assertLess(abs(second.rect.y1 - expected.y1), 1.0)
        page = document._doc[5]
        wrong = page.search_for("일반")[0]
        self.assertGreater(abs(second.rect.y0 - wrong.y0), 10.0)
        snippet = _search_snippet(document, second)
        self.assertIn("일반", snippet)
        self.assertNotIn("사업수행", snippet)
        document.close()

    def test_ascii_case_insensitive(self) -> None:
        src = fitz.open()
        page = src.new_page()
        page.insert_text((72, 72), "hello General world", fontsize=12)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.pdf"
            src.save(path)
            src.close()
            document = PdfDocument()
            document.open_file(str(path))
            hits = document.search_text("general")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].page_index, 0)
            document.close()


if __name__ == "__main__":
    unittest.main()
