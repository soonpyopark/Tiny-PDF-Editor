"""도형 그리기(표준 주석): 그리기·다시 고치기·삭제·되돌리기·저장 후 다시 열기·쪽 회전."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_editor.document import PdfDocument
from pdf_editor.shape_annot import (
    KINDS,
    SHAPE_ANNOT_TITLE,
    clean_hex,
    clean_points,
    normalize_params,
)

W, H = 300, 200


def _make_pdf(tmp: str, *, rotation: int = 0) -> str:
    src = fitz.open()
    page = src.new_page(width=W, height=H)
    if rotation:
        page.set_rotation(rotation)
    path = Path(tmp) / "base.pdf"
    src.save(path)
    src.close()
    return str(path)


def _open(path: str) -> PdfDocument:
    document = PdfDocument()
    document.open_file(path)
    return document


def _px(document: PdfDocument, x: float, y: float, zoom: float = 2.0, page: int = 0):
    pix = document.render_page_pixmap(page, zoom)
    i = int(y * zoom) * pix.stride + int(x * zoom) * pix.n
    return tuple(pix.samples[i : i + 3])


def _add(document: PdfDocument, kind: str, params=None, page: int = 0) -> int:
    rect_geom = {"rect": [40, 30, 140, 90]}
    point_geom = {"points": [[40, 30], [140, 40], [120, 100], [50, 90]][: 2 if kind in ("line", "arrow", "polyline") else 4]}
    geom = point_geom if kind in ("line", "arrow", "polygon", "cloud", "polyline") else rect_geom
    return document.add_shape(page, kind, geom, params)


class ParamsTests(unittest.TestCase):
    def test_clean_hex(self) -> None:
        self.assertEqual(clean_hex("#ABC", None), "#aabbcc")
        self.assertEqual(clean_hex("ff0000", None), "#ff0000")
        self.assertEqual(clean_hex("red", "#000000"), "#000000")

    def test_normalize_clamps(self) -> None:
        params = normalize_params({"width": 999, "opacity": -1, "fontSize": 1, "fill": "zzz", "align": 9}, "rect")
        self.assertEqual(params["width"], 40.0)
        self.assertEqual(params["opacity"], 0.05)
        self.assertEqual(params["fontSize"], 4.0)
        self.assertIsNone(params["fill"])
        self.assertEqual(params["align"], 0)

    def test_line_has_no_fill_and_text_may_have_zero_border(self) -> None:
        self.assertIsNone(normalize_params({"fill": "#ffffff"}, "line")["fill"])
        self.assertEqual(normalize_params({"width": 0}, "text")["width"], 0.0)
        self.assertEqual(normalize_params({"width": 0}, "rect")["width"], 0.25)

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_params({}, "star")

    def test_points_need_enough_distinct_points(self) -> None:
        with self.assertRaises(ValueError):
            clean_points([[1, 1], [1, 1]], "line")
        with self.assertRaises(ValueError):
            clean_points([[1, 1], [5, 5]], "polygon")
        self.assertEqual(len(clean_points([[0, 0], [10, 0], [10, 10], [0, 0]], "polygon")), 3)


class ShapeTests(unittest.TestCase):
    def test_every_kind_roundtrips_geometry_on_every_rotation(self) -> None:
        for rotation in (0, 90, 180, 270):
            with tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                sizes = {kind: _add(document, kind, {"text": "가나다"} if kind == "text" else None) for kind in KINDS}
                items = {item["kind"]: item for item in document.shape_items()}
                self.assertEqual(set(items), set(KINDS), f"rotation {rotation}")
                for kind, item in items.items():
                    self.assertEqual(item["id"], sizes[kind])
                    if "rect" in item:
                        for got, want in zip(item["rect"], [40, 30, 140, 90]):
                            self.assertAlmostEqual(got, want, delta=0.05, msg=f"{kind} rot {rotation}")
                    else:
                        want = [[40, 30], [140, 40], [120, 100], [50, 90]][: len(item["points"])]
                        for got_pt, want_pt in zip(item["points"], want):
                            self.assertAlmostEqual(got_pt[0], want_pt[0], delta=0.05, msg=f"{kind} rot {rotation}")
                            self.assertAlmostEqual(got_pt[1], want_pt[1], delta=0.05, msg=f"{kind} rot {rotation}")

    def test_titles_and_ink_are_not_mixed_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _add(document, "rect")
            document.add_ink_strokes(0, [[[10, 10], [60, 60]]], rgb=(1, 0, 0), width=2.0, opacity=1.0)
            page = document._doc[0]
            titles = sorted((a.info or {}).get("title") for a in page.annots())
            self.assertIn(SHAPE_ANNOT_TITLE, titles)
            self.assertEqual(len(document.shape_items()), 1)

    def test_filled_rect_paints_where_drawn_and_not_elsewhere(self) -> None:
        for rotation in (0, 90, 270):
            with tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                _add(document, "rect", {"fill": "#00ff00", "color": "#0000ff", "width": 2})
                self.assertEqual(_px(document, 90, 60), (0, 255, 0), f"rotation {rotation}")
                self.assertEqual(_px(document, 250, 150), (255, 255, 255))
                self.assertEqual(_px(document, 40, 60), (0, 0, 255))  # 왼쪽 테두리

    def test_ellipse_corner_stays_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _add(document, "ellipse", {"fill": "#ff0000"})
            self.assertEqual(_px(document, 90, 60), (255, 0, 0))
            self.assertEqual(_px(document, 43, 33), (255, 255, 255))

    def test_text_box_shows_text_with_border_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _add(document, "text", {"text": "한글 Hello", "fill": "#ffffe0", "color": "#ff0000", "width": 3, "fontSize": 16})
            self.assertEqual(_px(document, 140, 60), (255, 0, 0))  # 오른쪽 테두리는 지정한 색
            near = _px(document, 132, 85)  # 안쪽 배경
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(near, (255, 255, 224))), near)
            item = document.shape_items()[0]
            self.assertEqual(item["params"]["text"], "한글 Hello")
            self.assertIn("Hello", document._doc[0].get_text())

    def test_text_box_edit_changes_text_and_keeps_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            old = _add(document, "text", {"text": "처음"})
            result = document.update_shape(0, old, None, {"text": "고친 글"})
            self.assertTrue(result["changed"])
            item = document.shape_items()[0]
            self.assertEqual(item["id"], result["newId"])
            self.assertEqual(item["params"]["text"], "고친 글")
            for got, want in zip(item["rect"], [40, 30, 140, 90]):
                self.assertAlmostEqual(got, want, delta=0.05)
            self.assertIn("고친", document._doc[0].get_text())
            self.assertNotIn("처음", document._doc[0].get_text())

    def test_special_characters_in_text_do_not_break(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _add(document, "text", {"text": "a < b & c > d\n둘째 줄"})
            self.assertEqual(document.shape_items()[0]["params"]["text"], "a < b & c > d\n둘째 줄")

    def test_move_and_restyle_updates_in_place_of_old_one(self) -> None:
        for rotation in (0, 90):
            with tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                old = _add(document, "rect", {"fill": "#00ff00"})
                result = document.update_shape(0, old, {"rect": [100, 120, 190, 180]}, {"fill": "#ff0000"})
                self.assertNotEqual(result["newId"], old)
                items = document.shape_items()
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["params"]["fill"], "#ff0000")
                self.assertEqual(_px(document, 90, 60), (255, 255, 255))
                self.assertEqual(_px(document, 145, 150), (255, 0, 0))

    def test_nothing_changed_makes_no_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _add(document, "rect")
            depth = len(document._undo_stack)
            result = document.update_shape(0, xref, {"rect": [40, 30, 140, 90]}, {"width": 2})
            self.assertFalse(result["changed"])
            self.assertEqual(result["newId"], xref)
            self.assertEqual(len(document._undo_stack), depth)

    def test_undo_redo_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _add(document, "polygon")
            self.assertEqual(len(document.shape_items()), 1)
            self.assertTrue(document.undo())
            self.assertEqual(len(document.shape_items()), 0)
            self.assertTrue(document.redo())
            self.assertEqual(len(document.shape_items()), 1)
            document.delete_shape(0, document.shape_items()[0]["id"])
            self.assertEqual(len(document.shape_items()), 0)
            self.assertTrue(document.undo())
            self.assertEqual(len(document.shape_items()), 1)
            self.assertIsInstance(xref, int)

    def test_survives_save_and_reopen_and_is_still_editable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            for kind in KINDS:
                _add(document, kind, {"text": "저장"} if kind == "text" else None)
            out = Path(tmp) / "out.pdf"
            document.save(str(out))
            reopened = _open(str(out))
            items = reopened.shape_items()
            self.assertEqual({item["kind"] for item in items}, set(KINDS))
            first = items[0]
            result = reopened.update_shape(0, first["id"], None, {"color": "#123456"})
            self.assertTrue(result["changed"])
            self.assertEqual(len(reopened.shape_items()), len(KINDS))

    def test_cloud_is_not_a_plain_polygon_and_dash_changes_look(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = _open(_make_pdf(tmp))
            b = _open(_make_pdf(tmp))
            c = _open(_make_pdf(tmp))
            _add(a, "polygon", {"width": 3})
            _add(b, "cloud", {"width": 3})
            _add(c, "polygon", {"width": 3, "dash": True})
            sa = a.render_page_pixmap(0, 2.0).samples
            self.assertNotEqual(sa, b.render_page_pixmap(0, 2.0).samples)
            self.assertNotEqual(sa, c.render_page_pixmap(0, 2.0).samples)

    def test_opacity_blends_with_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _add(document, "rect", {"fill": "#000000", "opacity": 0.5, "color": "#000000"})
            r, g, b = _px(document, 90, 60)
            self.assertTrue(100 < r < 160, (r, g, b))

    def test_wrong_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            with self.assertRaises(ValueError):
                document.update_shape(0, 9999, None, {"width": 3})
            with self.assertRaises(ValueError):
                document.delete_shape(5, 1)
            with self.assertRaises(ValueError):
                document.add_shape(0, "rect", {"rect": [10, 10, 10.2, 10.2]}, None)


if __name__ == "__main__":
    unittest.main()
