"""인쇄용 쪽 그림(printPage) 엔진 연산 테스트."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from pdf_editor.document import PdfDocument
from pdf_editor.engine import _handle


def _make_pdf(tmp: str, *, with_photo: bool = False) -> str:
    src = fitz.open()
    page = src.new_page(width=300, height=200)
    page.draw_rect(fitz.Rect(0, 0, 150, 200), color=None, fill=(1, 0, 0))
    if with_photo:
        # 압축이 거의 안 되는 큰 잡음 그림 → PNG 가 한도를 넘는다
        import os

        noise = Image.frombytes("RGB", (1800, 2400), os.urandom(1800 * 2400 * 3))
        photo = Path(tmp) / "noise.jpg"
        noise.save(photo, quality=100, subsampling=0)
        page.insert_image(fitz.Rect(150, 0, 300, 200), filename=str(photo))
    path = Path(tmp) / "doc.pdf"
    src.save(path)
    src.close()
    return str(path)


def _open(path: str) -> PdfDocument:
    document = PdfDocument()
    document.open_file(path)
    return document


class PrintPageTests(unittest.TestCase):
    def test_renders_png_at_requested_zoom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _, result = _handle(
                document, True, {"op": "printPage", "index": 0, "zoom": 4.0, "path": str(Path(tmp) / "p0")}
            )
            self.assertTrue(result["path"].endswith(".png"))
            self.assertEqual((result["width"], result["height"]), (1200, 800))
            with Image.open(result["path"]) as img:
                self.assertEqual(img.size, (1200, 800))
                self.assertEqual(img.mode, "RGB")
                self.assertEqual(img.getpixel((10, 10)), (255, 0, 0))
                self.assertEqual(img.getpixel((1100, 700)), (255, 255, 255))

    def test_gray_mode_writes_single_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _, result = _handle(
                document, True, {"op": "printPage", "index": 0, "zoom": 1.0, "path": str(Path(tmp) / "g"), "gray": True}
            )
            with Image.open(result["path"]) as img:
                self.assertEqual(img.mode, "L")

    def test_big_photo_page_falls_back_to_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp, with_photo=True))
            _, result = _handle(
                document, True, {"op": "printPage", "index": 0, "zoom": 8.0, "path": str(Path(tmp) / "photo")}
            )
            self.assertTrue(result["path"].endswith(".jpg"), result["path"])
            self.assertFalse((Path(tmp) / "photo.png").exists())
            with Image.open(result["path"]) as img:
                self.assertEqual(img.format, "JPEG")

    def test_zoom_is_capped_for_print(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _, result = _handle(
                document, True, {"op": "printPage", "index": 0, "zoom": 50, "path": str(Path(tmp) / "cap")}
            )
            self.assertEqual(result["width"], round(300 * 8.4))

    def test_rejects_bad_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            with self.assertRaises(ValueError):
                _handle(document, True, {"op": "printPage", "index": 9, "path": str(Path(tmp) / "x")})
            with self.assertRaises(ValueError):
                _handle(document, True, {"op": "printPage", "index": 0, "path": str(Path(tmp) / "nope" / "x")})
            with self.assertRaises(ValueError):
                _handle(document, False, {"op": "printPage", "index": 0, "path": str(Path(tmp) / "x")})


if __name__ == "__main__":
    unittest.main()
