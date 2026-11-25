"""그리기(자유 곡선 잉크 주석): 추가·렌더·회전·지우개·실행 취소·저장."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_editor.document import PdfDocument
from pdf_editor.ink_draw import (
    INK_ANNOT_TITLE,
    clean_rgb,
    clean_strokes,
    polyline_distance,
    stroke_hit_by_path,
)


def _make_pdf(tmp: str, *, rotation: int = 0, name: str = "base.pdf", pages: int = 1) -> str:
    src = fitz.open()
    for _ in range(pages):
        page = src.new_page(width=300, height=200)
        if rotation:
            page.set_rotation(rotation)
    path = Path(tmp) / name
    src.save(path)
    src.close()
    return str(path)


def _open(path: str) -> PdfDocument:
    document = PdfDocument()
    document.open_file(path)
    return document


def _pixel(pix: fitz.Pixmap, x: int, y: int) -> tuple[int, int, int]:
    i = y * pix.stride + x * pix.n
    s = pix.samples
    return (s[i], s[i + 1], s[i + 2])


def _dark_bbox(pix: fitz.Pixmap, threshold: int = 200):
    xs: list[int] = []
    ys: list[int] = []
    s = pix.samples
    for y in range(pix.height):
        for x in range(pix.width):
            i = y * pix.stride + x * pix.n
            if s[i] < threshold or s[i + 1] < threshold or s[i + 2] < threshold:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _ink_count(document: PdfDocument, page_index: int = 0) -> int:
    page = document._doc[page_index]
    return sum(
        1
        for annot in document._iter_page_annots(page)
        if annot.type and annot.type[0] == fitz.PDF_ANNOT_INK
    )


class InkGeometryTests(unittest.TestCase):
    def test_clean_strokes_clamps_drops_and_dots(self) -> None:
        bounds = fitz.Rect(0, 0, 100, 100)
        strokes = clean_strokes(
            [
                [(-50, -50), (500, 500)],
                [(10, 10)],
                [("x", 1), (None, 2)],
                "not a stroke",
                [],
                [(5, 5), (5, 5), (5, 5)],
            ],
            bounds,
        )
        self.assertEqual(strokes[0], [(0.0, 0.0), (100.0, 100.0)])
        self.assertEqual(len(strokes[1]), 2)  # 한 점 -> 점 하나가 남는 짧은 획
        self.assertEqual(len(strokes[2]), 2)  # 같은 점 반복 -> 같은 처리
        self.assertEqual(len(strokes), 3)

    def test_clean_strokes_rejects_non_finite(self) -> None:
        bounds = fitz.Rect(0, 0, 100, 100)
        self.assertEqual(clean_strokes([[(float("nan"), 1), (float("inf"), 2)]], bounds), [])
        self.assertEqual(clean_strokes(None, bounds), [])

    def test_clean_rgb(self) -> None:
        self.assertEqual(clean_rgb([1, 0, 0]), (1.0, 0.0, 0.0))
        self.assertEqual(clean_rgb([255, 128, 0])[0], 1.0)
        self.assertEqual(len(clean_rgb("junk")), 3)
        self.assertEqual(len(clean_rgb(None)), 3)

    def test_polyline_distance_and_hit(self) -> None:
        a = [(0.0, 0.0), (100.0, 0.0)]
        crossing = [(50.0, -10.0), (50.0, 10.0)]
        self.assertEqual(polyline_distance(a, crossing), 0.0)
        far = [(0.0, 30.0), (100.0, 30.0)]
        self.assertAlmostEqual(polyline_distance(a, far), 30.0)
        self.assertTrue(stroke_hit_by_path(a, 4.0, far, 30.0))
        self.assertFalse(stroke_hit_by_path(a, 4.0, far, 10.0))
        # 한 점짜리 지우개도 동작
        self.assertTrue(stroke_hit_by_path(a, 4.0, [(50.0, 5.0)], 4.0))


class InkAddTests(unittest.TestCase):
    def test_add_marks_modified_and_draws_where_drawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            self.assertFalse(document.modified)
            added = document.add_ink_strokes(0, [[(20, 20), (100, 20)]], rgb=(0, 0, 0), width=4)
            self.assertEqual(added, 1)
            self.assertTrue(document.modified)
            bbox = _dark_bbox(document.render_page_pixmap(0, 1.0))
            self.assertIsNotNone(bbox)
            x0, y0, x1, y1 = bbox
            self.assertLessEqual(abs(x0 - 18), 2)
            self.assertLessEqual(abs(x1 - 102), 2)
            self.assertLessEqual(abs(y0 - 18), 2)
            self.assertLessEqual(abs(y1 - 22), 2)
            document.close()

    def test_rotated_pages_draw_where_the_user_drew(self) -> None:
        # 화면(회전 반영) 좌표 (20,20)-(100,20) 가로선은 어떤 회전에서도 화면 같은 자리에 보여야 한다.
        for rotation in (90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                document.add_ink_strokes(0, [[(20, 20), (100, 20)]], rgb=(0, 0, 0), width=4)
                bbox = _dark_bbox(document.render_page_pixmap(0, 1.0))
                self.assertIsNotNone(bbox)
                x0, y0, x1, y1 = bbox
                self.assertLessEqual(abs(x0 - 18), 2, bbox)
                self.assertLessEqual(abs(x1 - 102), 2, bbox)
                self.assertLessEqual(abs(y0 - 18), 2, bbox)
                self.assertLessEqual(abs(y1 - 22), 2, bbox)
                document.close()

    def test_color_and_opacity_in_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(20, 50), (200, 50)]], rgb=(1, 0, 0), width=20, opacity=0.3)
            r, g, b = _pixel(document.render_page_pixmap(0, 1.0), 100, 50)
            # 흰 종이 위 빨강 30% = (255, ~178, ~178). 색이 이중으로 연해지면 R 이 ~200 으로 떨어진다.
            self.assertGreaterEqual(r, 253)
            self.assertTrue(172 <= g <= 184, (r, g, b))
            self.assertTrue(172 <= b <= 184, (r, g, b))
            document.close()

    def test_picked_color_is_rendered_exactly(self) -> None:
        # 색 팔레트에서 고른 색이 미리보기에서 달라 보이면 안 된다 (ICC 변환으로 흐려지던 문제).
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(20, 50), (200, 50)]], rgb=(0, 0.4, 1), width=20)
            r, g, b = _pixel(document.render_page_pixmap(0, 1.0), 100, 50)
            self.assertLessEqual(abs(r - 0), 3)
            self.assertLessEqual(abs(g - 102), 3)
            self.assertLessEqual(abs(b - 255), 3)
            document.close()

    def test_overlap_of_translucent_strokes_is_darker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(
                0,
                [[(20, 50), (200, 50)], [(100, 20), (100, 80)]],
                rgb=(1, 0.9, 0),
                width=16,
                opacity=0.4,
            )
            pix = document.render_page_pixmap(0, 1.0)
            single = _pixel(pix, 40, 50)
            both = _pixel(pix, 100, 50)
            self.assertLess(both[2], single[2])
            document.close()

    def test_ink_is_tagged_and_survives_save_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(20, 20), (100, 80), (180, 30)]], rgb=(0, 0, 1), width=3)
            out = Path(tmp) / "out.pdf"
            document.save(str(out))
            document.close()
            reopened = _open(str(out))
            page = reopened._doc[0]
            annots = [a for a in reopened._iter_page_annots(page) if a.type[0] == fitz.PDF_ANNOT_INK]
            self.assertEqual(len(annots), 1)
            self.assertEqual(annots[0].info.get("title"), INK_ANNOT_TITLE)
            self.assertIsNotNone(_dark_bbox(reopened.render_page_pixmap(0, 1.0)))
            reopened.close()

    def test_bad_page_index_and_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            with self.assertRaises(ValueError):
                document.add_ink_strokes(5, [[(1, 1), (2, 2)]], rgb=(0, 0, 0), width=2)
            self.assertEqual(document.add_ink_strokes(0, [], rgb=(0, 0, 0), width=2), 0)
            self.assertFalse(document.modified)
            self.assertFalse(document.can_undo())
            document.close()


class InkUndoTests(unittest.TestCase):
    def test_each_call_is_one_undo_step_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(10, 10), (50, 10)]], rgb=(0, 0, 0), width=2)
            document.add_ink_strokes(0, [[(10, 30), (50, 30)]], rgb=(0, 0, 0), width=2)
            self.assertEqual(_ink_count(document), 2)
            self.assertTrue(document.undo())
            self.assertEqual(_ink_count(document), 1)
            self.assertTrue(document.undo())
            self.assertEqual(_ink_count(document), 0)
            document.close()

    def test_continue_group_joins_previous_stroke_into_one_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(10, 10), (50, 10)]], rgb=(0, 0, 0), width=2)
            document.add_ink_strokes(0, [[(10, 30), (50, 30)]], rgb=(0, 0, 0), width=2, continue_group=True)
            document.add_ink_strokes(0, [[(10, 50), (50, 50)]], rgb=(0, 0, 0), width=2, continue_group=True)
            self.assertEqual(_ink_count(document), 3)
            self.assertTrue(document.undo())
            self.assertEqual(_ink_count(document), 0)
            self.assertFalse(document.can_undo())
            document.close()

    def test_continue_group_does_not_swallow_other_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp, pages=1))
            document.add_ink_strokes(0, [[(10, 10), (50, 10)]], rgb=(0, 0, 0), width=2)
            document.insert_blank_page_at(1)  # 그 사이 다른 편집
            document.add_ink_strokes(0, [[(10, 30), (50, 30)]], rgb=(0, 0, 0), width=2, continue_group=True)
            self.assertEqual(_ink_count(document), 2)
            self.assertTrue(document.undo())  # 두 번째 획만 취소돼야 한다
            self.assertEqual(_ink_count(document), 1)
            self.assertEqual(len(document._doc), 2)
            document.close()

    def test_continue_group_after_undo_starts_new_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(10, 10), (50, 10)]], rgb=(0, 0, 0), width=2)
            document.add_ink_strokes(0, [[(10, 30), (50, 30)]], rgb=(0, 0, 0), width=2)
            document.undo()
            document.add_ink_strokes(0, [[(10, 70), (50, 70)]], rgb=(0, 0, 0), width=2, continue_group=True)
            self.assertEqual(_ink_count(document), 2)
            self.assertTrue(document.undo())
            self.assertEqual(_ink_count(document), 1)
            document.close()

    def test_redo_restores_ink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(10, 10), (50, 10)]], rgb=(0, 0, 0), width=2)
            document.undo()
            self.assertEqual(_ink_count(document), 0)
            self.assertTrue(document.redo())
            self.assertEqual(_ink_count(document), 1)
            document.close()


class InkEraseTests(unittest.TestCase):
    def test_erase_removes_only_touched_strokes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(
                0,
                [[(20, 20), (120, 20)], [(20, 100), (120, 100)]],
                rgb=(0, 0, 0),
                width=4,
            )
            removed = document.erase_ink_near(0, [(70, 10), (70, 30)], radius=5)
            self.assertEqual(removed, 1)
            self.assertEqual(_ink_count(document), 1)
            bbox = _dark_bbox(document.render_page_pixmap(0, 1.0))
            self.assertGreater(bbox[1], 90)  # 남은 건 아래 획
            document.close()

    def test_erase_miss_changes_nothing_and_makes_no_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(20, 20), (120, 20)]], rgb=(0, 0, 0), width=4)
            before = len(document._undo_stack)
            self.assertEqual(document.erase_ink_near(0, [(200, 150)], radius=5), 0)
            self.assertEqual(len(document._undo_stack), before)
            self.assertEqual(_ink_count(document), 1)
            document.close()

    def test_erase_leaves_foreign_ink_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = fitz.open()
            page = src.new_page(width=300, height=200)
            annot = page.add_ink_annot([[(20, 20), (120, 20)]])  # 다른 프로그램이 넣은 잉크(표식 없음)
            annot.set_border(width=4)
            annot.update()
            path = Path(tmp) / "foreign.pdf"
            src.save(path)
            src.close()
            document = _open(str(path))
            self.assertEqual(document.erase_ink_near(0, [(70, 20)], radius=10), 0)
            self.assertEqual(_ink_count(document), 1)
            document.close()

    def test_erase_on_rotated_pages_uses_view_coordinates(self) -> None:
        for rotation in (90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                document.add_ink_strokes(0, [[(20, 20), (100, 20)]], rgb=(0, 0, 0), width=4)
                # 엉뚱한 자리(회전 전 좌표로 따졌을 때 닿을 만한 곳)는 안 지워져야 한다
                self.assertEqual(document.erase_ink_near(0, [(60, 90), (60, 120)], radius=4), 0)
                # 그린 자리를 지나가면 지워진다
                self.assertEqual(document.erase_ink_near(0, [(60, 10), (60, 30)], radius=4), 1)
                self.assertEqual(_ink_count(document), 0)
                document.close()

    def test_erase_group_and_undo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(
                0,
                [[(20, 20), (120, 20)], [(20, 60), (120, 60)]],
                rgb=(0, 0, 0),
                width=4,
            )
            self.assertEqual(document.erase_ink_near(0, [(40, 10), (40, 30)], radius=4), 1)
            self.assertEqual(
                document.erase_ink_near(0, [(40, 50), (40, 70)], radius=4, continue_group=True), 1
            )
            self.assertEqual(_ink_count(document), 0)
            self.assertTrue(document.undo())  # 지우기 묶음 취소 -> 둘 다 돌아옴
            self.assertEqual(_ink_count(document), 2)
            document.close()

    def test_ink_items_and_delete_ink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            document.add_ink_strokes(0, [[(20, 20), (120, 20)]], rgb=(0, 0, 0), width=4)
            document.add_ink_strokes(0, [[(20, 60), (120, 60)]], rgb=(1, 0, 0), width=6)
            items = document.ink_items(0)
            self.assertEqual(len(items), 2)
            for item in items:
                self.assertEqual(item["kind"], "ink")
                self.assertIsInstance(item["id"], int)
                self.assertEqual(len(item["rect"]), 4)
                self.assertTrue(item["strokes"])
            target = items[0]["id"]
            document.delete_ink(0, target)
            left = document.ink_items(0)
            self.assertEqual(len(left), 1)
            self.assertNotEqual(left[0]["id"], target)
            self.assertEqual(_ink_count(document), 1)
            self.assertTrue(document.undo())
            self.assertEqual(len(document.ink_items(0)), 2)
            document.close()


if __name__ == "__main__":
    unittest.main()
