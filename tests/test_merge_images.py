"""PDF 변환 > 하나의 PDF로 병합: PDF 와 이미지를 한 목록에서 섞어 병합할 수 있어야 한다."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_editor import engine


def _make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 60), f"pdf page {i + 1}", fontsize=18)
    doc.save(path)
    doc.close()


def _make_image(path: Path, size: tuple[int, int], rgb: tuple[int, int, int]) -> None:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, *size), False)
    pix.set_rect(pix.irect, rgb)
    pix.save(path)


class MergeImagesTests(unittest.TestCase):
    def test_pdf_and_images_merge_in_list_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "a.pdf"
            png = root / "b.png"
            jpg = root / "c.jpg"
            _make_pdf(pdf, 2)
            _make_image(png, (200, 100), (200, 60, 60))
            _make_image(jpg, (100, 200), (60, 60, 200))
            out = root / "merged.pdf"
            result = engine._merge_files_to_path([str(png), str(pdf), str(jpg)], str(out), {})
            self.assertEqual(result["pages"], 4)
            merged = fitz.open(out)
            try:
                self.assertEqual(len(merged), 4)
                # 순서: 이미지(png) -> pdf 2쪽 -> 이미지(jpg)
                self.assertEqual(len(merged[0].get_images()), 1)
                self.assertIn("pdf page 1", merged[1].get_text())
                self.assertIn("pdf page 2", merged[2].get_text())
                self.assertEqual(len(merged[3].get_images()), 1)
            finally:
                merged.close()

    def test_images_only_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "1.png"
            second = root / "2.png"
            _make_image(first, (120, 80), (10, 200, 10))
            _make_image(second, (80, 120), (200, 200, 10))
            out = root / "images.pdf"
            result = engine._merge_files_to_path([str(first), str(second)], str(out), {})
            self.assertEqual(result["pages"], 2)

    def test_inspect_counts_image_as_one_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            png = root / "x.png"
            pdf = root / "y.pdf"
            _make_image(png, (50, 50), (1, 2, 3))
            _make_pdf(pdf, 3)
            items = engine._merge_inspect([str(png), str(pdf)], {})
            self.assertEqual([item["pages"] for item in items], [1, 3])


if __name__ == "__main__":
    unittest.main()
