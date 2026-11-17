"""이미지 넣기(스탬프 주석): 넣기·다시 고치기·복사·여러 쪽·굳히기."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from pdf_editor.document import PdfDocument
from pdf_editor.image_stamp import (
    IMAGE_ANNOT_TITLE,
    apply_patch,
    default_params,
    final_image,
    natural_aspect,
    normalize_params,
    normalize_source,
    preview_png,
)

RED = (255, 0, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)


def _image_bytes(size=(200, 100)) -> bytes:
    """왼쪽 반 빨강(왼쪽 위 모서리에 파랑 점), 오른쪽 반 흰색 종이."""
    img = Image.new("RGB", size, WHITE)
    img.paste(RED, (0, 0, size[0] // 2, size[1]))
    img.paste(BLUE, (0, 0, 12, 12))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf(tmp: str, *, rotation: int = 0, pages: int = 1, fill=None) -> str:
    src = fitz.open()
    for _ in range(pages):
        page = src.new_page(width=300, height=200)
        if fill:
            page.draw_rect(page.rect, color=None, fill=fill)
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


def _px(document: PdfDocument, page: int, x: float, y: float, zoom: float = 2.0):
    pix = document.render_page_pixmap(page, zoom)
    i = int(y * zoom) * pix.stride + int(x * zoom) * pix.n
    return tuple(pix.samples[i : i + 3])


def _stamp(document: PdfDocument, view_rect, *, page: int = 0, params=None, source=None) -> int:
    source = source or normalize_source(_image_bytes())[0]
    return document.add_image_stamp(page, source, fitz.Rect(view_rect), params)


class ParamsTests(unittest.TestCase):
    def test_normalize_clamps_and_defaults(self) -> None:
        params = normalize_params({"op": 500, "rot": 450, "crop": [0.9, 0.9, 0.9, 0.9], "bg": {"tol": -5, "color": [999, 0, 0]}})
        self.assertEqual(params["op"], 100)
        self.assertEqual(params["rot"], 90)
        self.assertLessEqual(params["crop"][0] + params["crop"][2], 0.95 + 1e-6)
        self.assertEqual(params["bg"]["tol"], 0)
        self.assertEqual(params["bg"]["color"], [255, 0, 0])

    def test_rotate_swaps_flips_and_rotates_crop(self) -> None:
        params = default_params((200, 100))
        params["crop"] = [0.1, 0.2, 0.3, 0.4]
        cw = apply_patch(params, {"rotate": 90})
        self.assertEqual(cw["rot"], 90)
        self.assertEqual(cw["crop"], [0.4, 0.1, 0.2, 0.3])
        ccw = apply_patch(cw, {"rotate": -90})
        self.assertEqual(ccw["rot"], 0)
        self.assertEqual(ccw["crop"], params["crop"])
        flipped = apply_patch(params, {"flip": "x"})
        self.assertTrue(flipped["fx"])
        self.assertEqual(flipped["crop"], [0.3, 0.2, 0.1, 0.4])

    def test_natural_aspect_follows_rotation_and_crop(self) -> None:
        params = default_params((200, 100))
        self.assertAlmostEqual(natural_aspect(params), 2.0)
        self.assertAlmostEqual(natural_aspect(apply_patch(params, {"rotate": 90})), 0.5)
        cropped = apply_patch(params, {"crop": [0.0, 0.0, 0.5, 0.0]})
        self.assertAlmostEqual(natural_aspect(cropped), 1.0)


class PipelineTests(unittest.TestCase):
    def _final(self, params, rotation=0):
        data, _mime = final_image(normalize_source(_image_bytes())[0], params, rotation)
        return Image.open(io.BytesIO(data)).convert("RGBA")

    def test_background_knockout_makes_white_transparent_but_keeps_red(self) -> None:
        params = apply_patch(default_params((200, 100)), {"bg": {"on": True}})
        img = self._final(params)
        self.assertEqual(img.getpixel((150, 50))[3], 0)  # 흰 종이 → 투명
        self.assertEqual(img.getpixel((50, 60)), (255, 0, 0, 255))  # 빨강은 그대로

    def test_knockout_off_keeps_white(self) -> None:
        img = self._final(default_params((200, 100)))
        self.assertEqual(img.getpixel((150, 50))[3], 255)

    def test_opacity_is_baked_into_alpha(self) -> None:
        img = self._final(apply_patch(default_params((200, 100)), {"op": 40}))
        self.assertAlmostEqual(img.getpixel((50, 60))[3], 102, delta=2)

    def test_rotate_flip_crop_change_pixels(self) -> None:
        base = default_params((200, 100))
        rotated = self._final(apply_patch(base, {"rotate": 90}))
        self.assertEqual(rotated.size, (100, 200))
        # 파랑 점은 왼쪽 위 → 시계방향 90도 뒤에는 오른쪽 위
        self.assertEqual(rotated.getpixel((95, 5))[:3], BLUE)
        mirrored = self._final(apply_patch(base, {"flip": "x"}))
        self.assertEqual(mirrored.getpixel((195, 5))[:3], BLUE)
        cropped = self._final(apply_patch(base, {"crop": [0.0, 0.0, 0.5, 0.0]}))
        self.assertEqual(cropped.size, (100, 100))
        self.assertEqual(cropped.getpixel((90, 50))[:3], RED)

    def test_page_rotation_is_precompensated(self) -> None:
        # 쪽이 시계방향 90도로 보이면, 그림은 반시계방향 90도로 미리 돌려 둔다 (가로세로가 바뀜).
        img = self._final(default_params((200, 100)), rotation=90)
        self.assertEqual(img.size, (100, 200))

    def test_preview_is_small_and_uncropped(self) -> None:
        big = normalize_source(_image_bytes((1800, 900)))[0]
        params = apply_patch(default_params((1800, 900)), {"crop": [0.1, 0.0, 0.1, 0.0]})
        data, width, height = preview_png(big, params)
        with Image.open(io.BytesIO(data)) as preview:
            self.assertLessEqual(max(preview.size), 900)
            self.assertAlmostEqual(preview.width / preview.height, 2.0, places=1)
        self.assertEqual((width, height), (1800, 900))


class StampTests(unittest.TestCase):
    def test_stamp_is_listed_with_view_rect_and_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            items = document.image_stamp_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], xref)
            for got, want in zip(items[0]["rect"], (50, 50, 150, 100)):
                self.assertAlmostEqual(got, want, places=2)
            self.assertEqual((items[0]["params"]["ow"], items[0]["params"]["oh"]), (200, 100))
            self.assertAlmostEqual(items[0]["aspect"], 2.0)
            page = document._doc[0]  # 주석이 쪽에 묶여 있으니 쪽 참조를 잡아 둔다
            annot = page.load_annot(xref)
            self.assertEqual(annot.info["title"], IMAGE_ANNOT_TITLE)
            self.assertEqual(annot.type[0], fitz.PDF_ANNOT_STAMP)

    def test_stamp_renders_exactly_in_the_box_on_every_rotation(self) -> None:
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as tmp:
                document = _open(_make_pdf(tmp, rotation=rotation))
                view = document.get_page_rect(0)
                box = (view.width * 0.2, view.height * 0.2, view.width * 0.7, view.height * 0.5)
                _stamp(document, box)
                x0, y0, x1, y1 = box
                w, h = x1 - x0, y1 - y0
                # 파랑 점은 상자의 왼쪽 위(똑바로), 빨강은 왼쪽 반, 오른쪽 반(흰 종이)은 흰색
                self.assertEqual(_px(document, 0, x0 + w * 0.02, y0 + h * 0.02), BLUE)
                self.assertEqual(_px(document, 0, x0 + w * 0.25, y0 + h * 0.7), RED)
                self.assertEqual(_px(document, 0, x0 + w * 0.75, y0 + h * 0.5), WHITE)
                # 상자 바깥은 그대로
                self.assertEqual(_px(document, 0, x0 - 6, y0 + h / 2), WHITE)
                self.assertEqual(_px(document, 0, x1 + 6, y0 + h / 2), WHITE)
                # 가장자리가 상자와 1pt 이내로 맞는다 (오른쪽 반이 투명이 아니라 흰색이므로 빨강 구간으로 확인)
                red_edge = x0 + w / 2
                self.assertEqual(_px(document, 0, red_edge - 2, y0 + h * 0.7), RED)
                self.assertEqual(_px(document, 0, red_edge + 2, y0 + h * 0.7), WHITE)

    def test_transparent_background_shows_the_page_below(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp, fill=(0.8, 0.9, 0.8)))
            _stamp(document, (50, 50, 250, 150), params={"bg": {"on": True}})
            shown = _px(document, 0, 200, 100)
            self.assertAlmostEqual(shown[0], 204, delta=3)  # 종이색이 아닌 쪽 배경(연두)이 보인다
            self.assertAlmostEqual(shown[1], 230, delta=3)
            self.assertEqual(_px(document, 0, 100, 120), RED)

    def test_survives_save_and_reopen_and_is_still_editable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _stamp(document, (50, 50, 150, 100), params={"op": 70, "bg": {"on": True, "tol": 33}})
            out = Path(tmp) / "out.pdf"
            document.save(str(out))
            reopened = _open(str(out))
            items = reopened.image_stamp_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["params"]["op"], 70)
            self.assertEqual(items[0]["params"]["bg"]["tol"], 33)
            source, params = reopened.image_stamp_source(0, items[0]["id"])
            self.assertGreater(len(source), 100)
            self.assertEqual(params["bg"]["on"], True)

    def test_other_stamps_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            page = document._doc[0]
            page.add_stamp_annot(fitz.Rect(10, 10, 100, 40), stamp=0)
            self.assertEqual(document.image_stamp_items(), [])

    def test_move_and_resize_without_look_change_keeps_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            result = document.update_image_stamps([{"pageIndex": 0, "id": xref, "rect": [100, 60, 260, 140]}])
            self.assertEqual(result, [{"id": xref, "newId": xref}])
            self.assertEqual(_px(document, 0, 130, 120), RED)
            self.assertEqual(_px(document, 0, 70, 70), WHITE)

    def test_look_change_rebuilds_and_returns_new_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp, fill=(0.8, 0.9, 0.8)))
            xref = _stamp(document, (50, 50, 250, 150))
            params = document.image_stamp_items()[0]["params"]
            params = apply_patch(params, {"bg": {"on": True}})
            result = document.update_image_stamps([{"pageIndex": 0, "id": xref, "params": params}])
            self.assertEqual(len(result), 1)
            new_id = result[0]["newId"]
            self.assertNotEqual(new_id, xref)
            self.assertEqual([item["id"] for item in document.image_stamp_items()], [new_id])
            self.assertAlmostEqual(_px(document, 0, 200, 100)[0], 204, delta=3)

    def test_lock_toggle_does_not_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            params = document.image_stamp_items()[0]["params"]
            params["lock"] = True
            result = document.update_image_stamps([{"pageIndex": 0, "id": xref, "params": params}])
            self.assertEqual(result, [{"id": xref, "newId": xref}])
            self.assertTrue(document.image_stamp_items()[0]["params"]["lock"])

    def test_nothing_changed_makes_no_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            depth = len(document._undo_stack)
            item = document.image_stamp_items()[0]
            self.assertEqual(
                document.update_image_stamps([{"pageIndex": 0, "id": xref, "rect": item["rect"], "params": item["params"]}]),
                [],
            )
            self.assertEqual(len(document._undo_stack), depth)

    def test_batch_update_is_one_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            a = _stamp(document, (10, 10, 90, 50))
            b = _stamp(document, (150, 100, 250, 150))
            depth = len(document._undo_stack)
            document.update_image_stamps(
                [
                    {"pageIndex": 0, "id": a, "rect": [20, 20, 100, 60]},
                    {"pageIndex": 0, "id": b, "rect": [160, 110, 260, 160]},
                ]
            )
            self.assertEqual(len(document._undo_stack), depth + 1)
            self.assertTrue(document.undo())
            rects = sorted(item["rect"][0] for item in document.image_stamp_items())
            self.assertEqual([round(v) for v in rects], [10, 150])

    def test_lift_hides_until_unlifted_and_never_reaches_undo_or_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            document.lift_image_stamps([{"pageIndex": 0, "id": xref}], True)
            self.assertEqual(_px(document, 0, 70, 90), WHITE)  # 걷어낸 동안은 안 보인다
            document.lift_image_stamps([{"pageIndex": 0, "id": xref}], False)
            self.assertEqual(_px(document, 0, 70, 90), RED)
            # 숨긴 채 저장해도 파일에는 보이는 상태로 남는다
            document.lift_image_stamps([{"pageIndex": 0, "id": xref}], True)
            out = Path(tmp) / "lifted.pdf"
            document.save(str(out))
            self.assertEqual(_px(_open(str(out)), 0, 70, 90), RED)
            # 숨긴 채 되돌리기 기록을 만들어도 되돌아간 문서에서 보인다
            document.lift_image_stamps([{"pageIndex": 0, "id": xref}], True)
            document.update_image_stamps([{"pageIndex": 0, "id": xref, "rect": [60, 60, 160, 110]}])
            self.assertTrue(document.undo())
            self.assertEqual(_px(document, 0, 70, 90), RED)

    def test_delete_and_undo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            self.assertEqual(document.delete_image_stamps([{"pageIndex": 0, "id": xref}]), 1)
            self.assertEqual(document.image_stamp_items(), [])
            self.assertEqual(_px(document, 0, 70, 90), WHITE)
            self.assertTrue(document.undo())
            self.assertEqual(len(document.image_stamp_items()), 1)

    def test_add_is_one_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            _stamp(document, (50, 50, 150, 100))
            self.assertTrue(document.undo())
            self.assertEqual(document.image_stamp_items(), [])

    def test_apply_to_other_pages_shares_image_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp, pages=4))
            xref = _stamp(document, (30, 20, 130, 70))
            done = document.apply_image_to_pages(0, xref, [0, 1, 2, 3])
            self.assertEqual(done, [1, 2, 3])
            self.assertEqual(len(document.image_stamp_items()), 4)
            for index in (1, 2, 3):
                self.assertEqual(_px(document, index, 50, 60), RED)
            out = Path(tmp) / "multi.pdf"
            document.save(str(out))
            single = Path(tmp) / "single.pdf"
            solo = _open(_make_pdf(tmp))
            _stamp(solo, (30, 20, 130, 70))
            solo.save(str(single))
            # 4쪽에 넣어도 이미지 데이터를 나눠 쓰므로 한 쪽일 때보다 크게 늘지 않는다.
            self.assertLess(out.stat().st_size, single.stat().st_size * 1.8)
            self.assertEqual(len(_open(str(out)).image_stamp_items()), 4)

    def test_apply_to_rotated_page_keeps_view_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = fitz.open()
            src.new_page(width=300, height=200)
            rotated = src.new_page(width=300, height=200)
            rotated.set_rotation(90)
            path = Path(tmp) / "mixed.pdf"
            src.save(path)
            document = _open(str(path))
            xref = _stamp(document, (30, 20, 130, 70))
            self.assertEqual(document.apply_image_to_pages(0, xref, [1]), [1])
            view = document.get_page_rect(1)
            item = [it for it in document.image_stamp_items() if it["pageIndex"] == 1][0]
            self.assertAlmostEqual(item["rect"][0] / view.width, 30 / 300, places=2)
            self.assertAlmostEqual(item["rect"][1] / view.height, 20 / 200, places=2)

    def test_flatten_makes_content_and_removes_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            xref = _stamp(document, (50, 50, 150, 100))
            document.flatten_image_stamp(0, xref, below=False)
            self.assertEqual(document.image_stamp_items(), [])
            self.assertEqual(_px(document, 0, 70, 90), RED)
            self.assertEqual(len(document._doc[0].get_images()), 1)

    def test_flatten_below_text_puts_image_under_the_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = _open(_make_pdf(tmp))
            page = document._doc[0]
            page.insert_text((60, 90), "HELLO", fontsize=30, color=(0, 0, 0))
            xref = _stamp(document, (50, 50, 150, 100))
            document.flatten_image_stamp(0, xref, below=True)
            # 글자 획(검정)이 빨강 위에 그대로 남아 있어야 한다
            pix = document.render_page_pixmap(0, 3.0)
            samples = pix.samples  # 속성을 부를 때마다 복사본이 만들어지니 한 번만 받는다
            dark = sum(1 for i in range(0, len(samples), pix.n) if samples[i] < 40 and samples[i + 1] < 40 and samples[i + 2] < 40)
            self.assertGreater(dark, 100)


class EngineProtocolTests(unittest.TestCase):
    """UI 가 실제로 부르는 엔진 연산 흐름."""

    def setUp(self) -> None:
        import base64

        from pdf_editor.engine import _handle

        self._b64 = base64
        self._handle = _handle
        self._tmp = tempfile.TemporaryDirectory()
        self.document = _open(_make_pdf(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(self, req: dict) -> dict:
        # 실제 통신에서는 요청마다 번호(id)가 붙는다. 스탬프 번호와 이름이 겹치면 응답이 영영 안 맞았던 적이 있다.
        _opened, result = self._handle(self.document, True, {"id": 987654, **req})
        return result

    def _prepare(self, **extra) -> dict:
        image = self._b64.b64encode(_image_bytes()).decode("ascii")
        return self._call({"op": "imagePrepare", "pageIndex": 0, "image": image, **extra})

    def test_prepare_preview_commit_edit_delete_flow(self) -> None:
        prepared = self._prepare()
        self.assertEqual(len(prepared["rect"]), 4)
        self.assertEqual(len(prepared["page"]), 4)
        self.assertAlmostEqual(prepared["aspect"], 2.0)
        self.assertTrue(prepared["token"])
        self.assertEqual((prepared["previewWidth"], prepared["previewHeight"]), (200, 100))

        # 흰 배경 투명 미리보기(원본은 그대로)
        patched = self._call({"op": "imagePreview", "token": prepared["token"], "params": prepared["params"], "patch": {"bg": {"on": True}}})
        self.assertTrue(patched["params"]["bg"]["on"])
        preview = Image.open(io.BytesIO(self._b64.b64decode(patched["preview"]))).convert("RGBA")
        self.assertEqual(preview.getpixel((150, 50))[3], 0)

        committed = self._call(
            {"op": "imageCommit", "token": prepared["token"], "pageIndex": 0, "rect": prepared["rect"], "params": patched["params"]}
        )
        self.assertNotIn("id", committed, "응답의 최상위 id 는 요청 번호와 겹치면 안 된다")
        xref = committed["stampId"]
        self.assertTrue(committed["doc"]["modified"])
        listed = self._call({"op": "imageList"})["items"]
        self.assertEqual([item["id"] for item in listed], [xref])
        self.assertTrue(listed[0]["params"]["bg"]["on"])

        # 이미 넣은 이미지의 미리보기: 회전
        rotated = self._call({"op": "imagePreview", "pageIndex": 0, "stampId": xref, "patch": {"rotate": 90}})
        self.assertEqual(rotated["params"]["rot"], 90)
        self.assertAlmostEqual(rotated["aspect"], 0.5)

        # 편집 중엔 숨기고(걷어냄), 고친 뒤 확정
        self._call({"op": "imageLift", "targets": [{"pageIndex": 0, "id": xref}], "lifted": True})
        self.assertTrue(self._call({"op": "imageList"})["items"][0]["lifted"])
        updated = self._call(
            {"op": "imageUpdate", "updates": [{"pageIndex": 0, "id": xref, "rect": [10, 10, 110, 60], "params": rotated["params"]}]}
        )
        new_id = updated["results"][0]["newId"]
        item = self._call({"op": "imageList", "pageIndex": 0})["items"][0]
        self.assertEqual(item["id"], new_id)
        self.assertFalse(item["lifted"])
        self.assertEqual(item["params"]["rot"], 90)

        # 복사용 원본 + 모양
        source = self._call({"op": "imageSource", "pageIndex": 0, "stampId": new_id})
        self.assertEqual(source["params"]["rot"], 90)
        self.assertAlmostEqual(source["sizePt"][0], 100, places=1)

        # 붙여넣기: 같은 모양으로 새 세션 → 확정
        pasted = self._call(
            {"op": "imagePrepare", "pageIndex": 0, "image": source["image"], "params": source["params"], "sizePt": source["sizePt"]}
        )
        self.assertEqual(pasted["params"]["rot"], 90)
        self.assertAlmostEqual(pasted["rect"][2] - pasted["rect"][0], 100, places=1)
        self._call({"op": "imageCommit", "token": pasted["token"], "pageIndex": 0, "rect": pasted["rect"], "params": pasted["params"]})
        self.assertEqual(len(self._call({"op": "imageList"})["items"]), 2)

        removed = self._call({"op": "imageDelete", "targets": [{"pageIndex": 0, "id": new_id}]})
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(len(self._call({"op": "imageList"})["items"]), 1)

    def test_expired_token_is_a_clear_error(self) -> None:
        with self.assertRaises(ValueError):
            self._call({"op": "imageCommit", "token": "nope", "pageIndex": 0, "rect": [10, 10, 60, 40]})

    def test_apply_pages_and_flatten_ops(self) -> None:
        src = fitz.open()
        for _ in range(3):
            src.new_page(width=300, height=200)
        path = Path(self._tmp.name) / "three.pdf"
        src.save(path)
        self.document = _open(str(path))
        prepared = self._prepare()
        xref = self._call({"op": "imageCommit", "token": prepared["token"], "pageIndex": 0, "rect": prepared["rect"], "params": prepared["params"]})["stampId"]
        applied = self._call({"op": "imageApplyPages", "pageIndex": 0, "stampId": xref, "pages": [1, 2]})
        self.assertEqual(applied["pages"], [1, 2])
        self.assertEqual(len(self._call({"op": "imageList"})["items"]), 3)
        self._call({"op": "imageFlatten", "pageIndex": 0, "stampId": xref, "below": True})
        self.assertEqual(len(self._call({"op": "imageList"})["items"]), 2)


if __name__ == "__main__":
    unittest.main()
