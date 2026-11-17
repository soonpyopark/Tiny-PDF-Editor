"""이미지 넣기: 쪽 위에 이미지를 올리고 확정한다 (서명과 달리 흰 배경을 지우지 않는다)."""

from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from pdf_editor.document import PdfDocument
from pdf_editor.engine import _handle, _placed_image_rect, _prepare_placed_image


def _make_pdf(tmp: str, *, rotation: int = 0) -> str:
    src = fitz.open()
    page = src.new_page(width=300, height=200)
    if rotation:
        page.set_rotation(rotation)
    path = Path(tmp) / "base.pdf"
    src.save(path)
    src.close()
    return str(path)


def _png(size: tuple[int, int], rgba: tuple[int, int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, rgba).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(size: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _open(path: str) -> PdfDocument:
    document = PdfDocument()
    document.open_file(path)
    return document


def _pixel(document: PdfDocument, x: int, y: int) -> tuple[int, int, int]:
    pix = document._doc[0].get_pixmap(alpha=False)
    i = y * pix.stride + x * pix.n
    return (pix.samples[i], pix.samples[i + 1], pix.samples[i + 2])


class PrepareImageTests(unittest.TestCase):
    def test_white_photo_keeps_its_white(self) -> None:
        data, mime, width, height = _prepare_placed_image(_png((40, 20), (255, 255, 255, 255)))
        self.assertEqual((mime, width, height), ("image/png", 40, 20))
        with Image.open(io.BytesIO(data)) as out:
            # 서명 처리와 달리 흰 이미지가 투명해지거나 잘리지 않는다.
            self.assertEqual(out.size, (40, 20))
            self.assertEqual(out.convert("RGB").getpixel((5, 5)), (255, 255, 255))

    def test_jpeg_without_changes_is_kept_as_is(self) -> None:
        raw = _jpeg((64, 48), (10, 120, 200))
        data, mime, width, height = _prepare_placed_image(raw)
        self.assertEqual((mime, width, height), ("image/jpeg", 64, 48))
        self.assertEqual(data, raw)

    def test_real_transparency_is_preserved(self) -> None:
        data, mime, _w, _h = _prepare_placed_image(_png((10, 10), (255, 0, 0, 80)))
        self.assertEqual(mime, "image/png")
        with Image.open(io.BytesIO(data)) as out:
            self.assertEqual(out.mode, "RGBA")
            self.assertEqual(out.getpixel((1, 1))[3], 80)

    def test_opaque_png_alpha_is_dropped(self) -> None:
        data, mime, _w, _h = _prepare_placed_image(_png((10, 10), (1, 2, 3, 255)))
        self.assertEqual(mime, "image/png")
        with Image.open(io.BytesIO(data)) as out:
            self.assertEqual(out.mode, "RGB")

    def test_huge_image_is_downscaled(self) -> None:
        _data, _mime, width, height = _prepare_placed_image(_png((4800, 1200), (9, 9, 9, 255)))
        self.assertEqual((width, height), (2400, 600))

    def test_garbage_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _prepare_placed_image(b"not an image")

    def test_initial_rect_is_centered_and_keeps_aspect(self) -> None:
        page = fitz.Rect(0, 0, 300, 200)
        rect = _placed_image_rect(page, 1000, 500)
        self.assertAlmostEqual((rect.x0 + rect.x1) / 2, 150, places=3)
        self.assertAlmostEqual((rect.y0 + rect.y1) / 2, 100, places=3)
        self.assertAlmostEqual(rect.width / rect.height, 2.0, places=3)
        self.assertLessEqual(rect.width, 150.001)
        tall = _placed_image_rect(page, 100, 1000)
        self.assertLessEqual(tall.height, 120.001)


class PlaceImageTests(unittest.TestCase):
    def test_place_draws_image_where_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.place_image(0, _png((20, 20), (255, 0, 0, 255)), fitz.Rect(50, 50, 150, 120))
            self.assertEqual(_pixel(document, 100, 85), (255, 0, 0))
            self.assertEqual(_pixel(document, 200, 150), (255, 255, 255))
            self.assertTrue(document.modified)

    def test_place_is_one_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.place_image(0, _png((20, 20), (255, 0, 0, 255)), fitz.Rect(50, 50, 150, 120))
            self.assertTrue(document.undo())
            self.assertEqual(_pixel(document, 100, 85), (255, 255, 255))

    def test_white_image_is_not_knocked_out_on_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            # 사진: 왼쪽 반 파랑, 오른쪽 반 흰색. 흰 부분도 그대로 흰색이어야 한다(투명 X).
            page = document._doc[0]
            page.draw_rect(fitz.Rect(0, 0, 300, 200), color=None, fill=(0.8, 0.8, 0.8))
            img = Image.new("RGB", (40, 20), (255, 255, 255))
            img.paste((0, 0, 255), (0, 0, 20, 20))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            document.place_image(0, buf.getvalue(), fitz.Rect(40, 40, 240, 140))
            self.assertEqual(_pixel(document, 200, 90), (255, 255, 255))
            self.assertEqual(_pixel(document, 80, 90), (0, 0, 255))

    def test_place_on_rotated_pages_lands_in_the_view_rect(self) -> None:
        for rotation in (90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                view = document.get_page_rect(0)
                rect = fitz.Rect(view.width * 0.2, view.height * 0.2, view.width * 0.6, view.height * 0.5)
                document.place_image(0, _png((20, 20), (255, 0, 0, 255)), rect)
                cx = int((rect.x0 + rect.x1) / 2)
                cy = int((rect.y0 + rect.y1) / 2)
                self.assertEqual(_pixel(document, cx, cy), (255, 0, 0))
                self.assertEqual(_pixel(document, int(view.width * 0.9), int(view.height * 0.9)), (255, 255, 255))

    def test_outside_page_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            with self.assertRaises(ValueError):
                document.place_image(0, _png((5, 5), (0, 0, 0, 255)), fitz.Rect(400, 400, 500, 500))

    def test_survives_save_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.place_image(0, _png((20, 20), (255, 0, 0, 255)), fitz.Rect(50, 50, 150, 120))
            out = Path(tmp) / "out.pdf"
            document.save(str(out))
            reopened = _open(str(out))
            self.assertEqual(len(reopened._doc[0].get_images()), 1)


class EngineOpsTests(unittest.TestCase):
    def test_prepare_then_commit_through_engine_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            opened = True
            image = base64.b64encode(_jpeg((120, 60), (200, 30, 30))).decode("ascii")
            _opened, prepared = _handle(document, opened, {"op": "imagePrepare", "pageIndex": 0, "image": image})
            self.assertEqual(prepared["mime"], "image/jpeg")
            self.assertEqual(len(prepared["rect"]), 4)
            self.assertEqual(len(prepared["page"]), 4)
            _opened, committed = _handle(
                document,
                opened,
                {"op": "imageCommit", "pageIndex": 0, "image": prepared["image"], "rect": prepared["rect"]},
            )
            self.assertTrue(committed["doc"]["modified"])
            self.assertEqual(len(document._doc[0].get_images()), 1)

    def test_prepare_requires_image_and_valid_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            opened = True
            with self.assertRaises(ValueError):
                _handle(document, opened, {"op": "imagePrepare", "pageIndex": 0, "image": ""})
            with self.assertRaises(ValueError):
                _handle(document, opened, {"op": "imagePrepare", "pageIndex": 5, "image": "AAAA"})


if __name__ == "__main__":
    unittest.main()
