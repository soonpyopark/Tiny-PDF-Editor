"""Headless PDF engine for Tiny PDF Editor Neo.

One JSON object per stdin line, one JSON object per stdout line. The Electron
host (``neo-app``) owns the UI, the virtual printer and the print-spool watcher;
this process only does document work.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import fitz

from pdf_editor.document import (
    OptimizeSizeOptions,
    PdfDocument,
    PdfPasswordRejected,
    PdfPasswordRequired,
    configure_mupdf_messages,
)
from pdf_editor.page_numbers import PageNumberOptions
from pdf_editor.signature_stamp import (
    SignatureStampHit,
    StampPlacementMemory,
    crop_alpha_bbox,
    knockout_white_rgba,
    reinforce_signature_ink,
    remember_stamp_placement,
    stamp_rect_from_memory,
)

_MAX_ZOOM = 5.0
_MIN_ZOOM = 0.2
_THUMB_WIDTH = 200


def _write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# 지금 처리 중인 요청 id. 진행 로그(type=log)를 같은 id 로 보내서 UI 터미널에 쌓는다.
_active_request_id = None


def _log(message: str) -> None:
    """Stream one progress line for the running request (does not finish it)."""
    _write({"type": "log", "id": _active_request_id, "message": str(message)})


def _image_progress_logger():
    last = {"text": ""}

    def report(current: int, total: int) -> None:
        text = f"  이미지 재압축 중... {current}/{total}"
        if text != last["text"]:
            last["text"] = text
            _log(text)

    return report


def _summary(doc: PdfDocument, opened: bool) -> dict:
    if not opened:
        return {"open": False, "name": "", "path": None, "pageCount": 0, "modified": False}
    return {
        "open": True,
        "name": doc.display_name,
        "path": doc.source_path,
        "pageCount": doc.page_count,
        "modified": doc.modified,
        "passwordProtected": doc.has_password_protection(),
    }


def _pii_preview_rects(doc: PdfDocument, hit) -> list[list[float]]:
    """Hit rectangles as 0..1 ratios of the page, for the review overlay."""
    from pdf_editor.pii_remove import tightened_hit_rects

    page = doc.get_page_rect(hit.page_index)
    width = max(1.0, float(page.width))
    height = max(1.0, float(page.height))
    return [
        [
            (rect.x0 - page.x0) / width,
            (rect.y0 - page.y0) / height,
            (rect.x1 - page.x0) / width,
            (rect.y1 - page.y0) / height,
        ]
        for rect in tightened_hit_rects(hit)
    ]


def _require_open(opened: bool) -> None:
    if not opened:
        raise ValueError("열린 문서가 없습니다.")


# 서명 넣기: 쪽마다 마지막 위치·크기를 기억해 다음 서명을 같은 자리에 놓는다(원본 StampPlacementMemory).
_stamp_memory: dict[str, StampPlacementMemory | None] = {"value": None}
# 기존 서명을 편집하려고 잠시 걷어낸 동안의 상태. 취소하면 이 값으로 되돌린다.
_signature_lift: dict = {"active": False, "modified": False}


def _prepare_signature(data: bytes) -> tuple[bytes, int, int]:
    """서명 이미지를 원본 앱과 같은 규칙으로 다듬는다: 흰 배경 투명화 → 연한 잉크 보강 → 빈 여백 자르기."""
    import io

    import numpy as np
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as src:
            rgba = np.array(src.convert("RGBA"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("이미지를 읽지 못했습니다.") from exc
    if rgba.shape[0] < 2 or rgba.shape[1] < 2:
        raise ValueError("이미지가 너무 작습니다.")
    rgba = reinforce_signature_ink(knockout_white_rgba(rgba))
    cropped = crop_alpha_bbox(rgba)
    if cropped is None:
        raise ValueError("서명으로 쓸 내용이 없는 이미지입니다. (전부 흰색입니다.)")
    height, width = cropped.shape[:2]
    buf = io.BytesIO()
    Image.fromarray(cropped, "RGBA").save(buf, format="PNG")
    return buf.getvalue(), int(width), int(height)


def _apply_launcher(req: dict[str, Any]) -> None:
    """파일 연결 대상을 엔진이 아니라 앱(Neo) 실행 파일로 맞춘다."""
    from pdf_editor.windows_file_assoc import set_launcher

    launcher = req.get("launcher")
    if isinstance(launcher, dict):
        set_launcher(launcher.get("exe"), launcher.get("command"))


def _rect_list(rect: fitz.Rect) -> list[float]:
    return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]


def _page_box(page: fitz.Rect) -> list[float]:
    """쪽 MediaBox [x0, y0, width, height]. 오버레이가 원점 보정에 쓴다."""
    return [float(page.x0), float(page.y0), float(page.width), float(page.height)]


def _rect_from_list(raw) -> fitz.Rect:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ValueError("서명 위치가 올바르지 않습니다.")
    return fitz.Rect(*(float(value) for value in raw))


def _signature_hit_json(hit: SignatureStampHit) -> dict:
    return {
        "pageIndex": hit.page_index,
        "annotXref": hit.annot_xref,
        "imageId": hit.image_id,
        "rect": _rect_list(hit.rect),
        "width": hit.width,
        "height": hit.height,
        "imageXref": hit.image_xref,
        "png": base64.b64encode(hit.png_bytes).decode("ascii"),
    }


def _signature_hit_from_json(raw) -> SignatureStampHit:
    if not isinstance(raw, dict):
        raise ValueError("서명 정보가 없습니다.")
    xref = raw.get("imageXref")
    return SignatureStampHit(
        page_index=int(raw["pageIndex"]),
        annot_xref=int(raw["annotXref"]),
        image_id=str(raw.get("imageId") or ""),
        rect=_rect_from_list(raw.get("rect")),
        width=int(raw.get("width") or 1),
        height=int(raw.get("height") or 1),
        png_bytes=b"",
        image_xref=int(xref) if xref else None,
    )


def _indices(req: dict, *, fallback: list[int] | None = None) -> list[int]:
    raw = req.get("indices")
    if raw is None:
        return list(fallback or [])
    return [int(value) for value in raw]


def _png(pix) -> dict:
    try:
        data = pix.tobytes("png")
        return {
            "png": base64.b64encode(data).decode("ascii"),
            "width": int(pix.width),
            "height": int(pix.height),
        }
    finally:
        pix = None


def _page_number_options(raw: dict | None) -> PageNumberOptions:
    data = raw if isinstance(raw, dict) else {}
    color = data.get("colorRgb") or data.get("color_rgb") or (0, 0, 0)
    background = data.get("backgroundRgb") or data.get("background_rgb") or (1, 1, 1)
    return PageNumberOptions(
        position=str(data.get("position") or "bottom_center"),
        style=str(data.get("style") or "arabic"),
        add_hyphens=bool(data.get("addHyphens", data.get("add_hyphens", True))),
        prefix=str(data.get("prefix") or ""),
        suffix=str(data.get("suffix") or ""),
        start_page=int(data.get("startPage", data.get("start_page", 1)) or 1),
        end_page=int(data.get("endPage", data.get("end_page", 0)) or 0),
        start_number=int(data.get("startNumber", data.get("start_number", 1)) or 1),
        font_size=float(data.get("fontSize", data.get("font_size", 12)) or 12),
        color_rgb=(float(color[0]), float(color[1]), float(color[2])),
        background_rgb=(float(background[0]), float(background[1]), float(background[2])),
        background_transparent=bool(
            data.get("backgroundTransparent", data.get("background_transparent", False))
        ),
        margin_x_mm=float(data.get("marginXmm", data.get("margin_x_mm", 12)) or 12),
        margin_y_mm=float(data.get("marginYmm", data.get("margin_y_mm", 10)) or 10),
    )


def _export_folder_name(display_name: str) -> str:
    """내보내기 폴더 이름에서 Windows 금지 문자를 치환한다."""
    base = str(display_name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    lower = base.lower()
    for ext in (".pdf", ".png", ".jpg", ".jpeg"):
        if lower.endswith(ext):
            base = base[: -len(ext)]
            break
    base = base.strip() or "문서"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).rstrip(" .")
    return cleaned or "문서"


def _page_number_options_payload(options: PageNumberOptions) -> dict:
    """_page_number_options 의 역변환. 대화상자 입력 키(camelCase)와 맞춘다."""
    return {
        "position": options.position,
        "style": options.style,
        "addHyphens": options.add_hyphens,
        "prefix": options.prefix,
        "suffix": options.suffix,
        "startPage": options.start_page,
        "endPage": options.end_page,
        "startNumber": options.start_number,
        "fontSize": options.font_size,
        "colorRgb": list(options.color_rgb),
        "backgroundRgb": list(options.background_rgb),
        "backgroundTransparent": options.background_transparent,
        "marginXmm": options.margin_x_mm,
        "marginYmm": options.margin_y_mm,
    }


_PREVIEW_WIDTH = 240


def _markup_point(raw, page_rect: fitz.Rect) -> fitz.Point:
    """Page point from a {x, y} request field given as 0..1 fractions of the shown page."""
    return fitz.Point(
        page_rect.x0 + float(raw["x"]) * page_rect.width,
        page_rect.y0 + float(raw["y"]) * page_rect.height,
    )


def _search_snippet(doc: PdfDocument, hit) -> str:
    """Text on the same line as a search hit (for the result row under the search box)."""
    rect = hit.rect
    if rect.is_empty or rect.is_infinite:
        return ""
    band = fitz.Rect(rect.x0 - 90, rect.y0, rect.x1 + 90, rect.y1)
    try:
        text = doc.get_text_in_rect(hit.page_index, band)
    except Exception:
        return ""
    return " ".join(text.split())[:200]


def _markup_rgb(raw) -> tuple[float, float, float]:
    red, green, blue = raw
    return (float(red), float(green), float(blue))


def _str_map(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value}


def _merge_password_resolver(passwords: dict[str, str]):
    """Feed known passwords to PdfDocument; otherwise stop and tell the UI which file needs one."""

    def resolve(path: str, rejected: bool) -> str | None:
        password = passwords.get(path)
        if password and not rejected:
            return password
        error_type = PdfPasswordRejected if rejected else PdfPasswordRequired
        error = error_type("비밀번호가 올바르지 않습니다." if rejected else "비밀번호가 필요합니다.")
        error.path = path
        raise error

    return resolve


def _merge_files_to_path(paths: list[str], output: str, passwords: dict[str, str]) -> dict:
    """Merge into a separate document so the one open in the editor is not touched."""
    merged = PdfDocument()
    try:
        added = merged.insert_files_at(
            0,
            paths,
            record_undo=False,
            resolve_pdf_password=_merge_password_resolver(passwords),
        )
        if merged.page_count < 1:
            raise ValueError("병합할 페이지가 없습니다.")
        saved = merged.save(output)
        return {"path": saved, "pages": merged.page_count, "added": added}
    finally:
        merged.close()


def _merge_inspect(paths: list[str], passwords: dict[str, str]) -> list[dict]:
    """Page counts for the merge list. Cheap: no rendering."""
    from pdf_editor.document import IMAGE_EXTENSIONS, PDF_EXTENSIONS

    items: list[dict] = []
    for raw in paths:
        ext = Path(raw).suffix.lower()
        entry: dict = {"path": raw, "pages": None}
        try:
            if ext in PDF_EXTENSIONS:
                src = PdfDocument._open_pdf_path(raw, passwords.get(raw))
                try:
                    entry["pages"] = len(src)
                finally:
                    src.close()
            elif ext in IMAGE_EXTENSIONS:
                entry["pages"] = 1
        except PdfPasswordRequired as exc:
            entry["needsPassword"] = True
            entry["rejected"] = isinstance(exc, PdfPasswordRejected)
        except Exception:
            pass
        items.append(entry)
    return items


def _preview_file(raw_path: str, password: str | None) -> dict:
    """First page of a file as PNG for the merge sidebar."""
    from pdf_editor.document import IMAGE_EXTENSIONS, PDF_EXTENSIONS
    from pdf_editor.hwp_convert import HWP_EXTENSIONS

    if not raw_path:
        raise ValueError("파일 경로가 없습니다.")
    target = Path(raw_path).expanduser().resolve()
    if not target.is_file():
        raise ValueError("파일을 찾을 수 없습니다.")
    ext = target.suffix.lower()
    if ext in HWP_EXTENSIONS:
        return {"unsupported": True}
    try:
        if ext in IMAGE_EXTENSIONS:
            src = fitz.open(str(target))
        elif ext in PDF_EXTENSIONS:
            src = PdfDocument._open_pdf_path(str(target), password)
        else:
            return {"unsupported": True}
    except PdfPasswordRequired as exc:
        return {"needsPassword": True, "rejected": isinstance(exc, PdfPasswordRejected)}
    try:
        if len(src) < 1:
            return {"unsupported": True}
        page = src[0]
        width = max(1.0, float(page.rect.width))
        zoom = _PREVIEW_WIDTH / width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return {**_png(pix), "pageCount": len(src)}
    finally:
        src.close()


def _handle(doc: PdfDocument, opened: bool, req: dict) -> tuple[bool, dict]:
    op = str(req.get("op") or "")
    if op == "ping":
        return opened, {"pong": True}
    if op == "info":
        return opened, {"doc": _summary(doc, opened)}
    if op == "close":
        doc.close()
        return False, {"doc": _summary(doc, False)}
    if op == "new":
        doc.new_document()
        return True, {"doc": _summary(doc, True)}
    if op == "open":
        raw_path = str(req.get("path") or "").strip()
        if not raw_path:
            raise ValueError("파일 경로가 없습니다.")
        target = Path(raw_path).expanduser().resolve()
        if not target.is_file():
            raise ValueError("파일을 찾을 수 없습니다.")
        password = req.get("password")
        password = str(password) if password else None
        doc.open_file(str(target), password=password)
        return True, {"doc": _summary(doc, True)}
    if op == "pageSizes":
        # 연속 스크롤에서 아직 그리지 않은 쪽의 자리를 잡는다. 단위는 pt (1/72 inch).
        if not opened:
            return opened, {"sizes": []}
        sizes = []
        for index in range(doc.page_count):
            rect = doc.get_page_rect(index)
            sizes.append([round(float(rect.width), 2), round(float(rect.height), 2)])
        return opened, {"sizes": sizes}
    if op == "render":
        _require_open(opened)
        index = int(req.get("index") or 0)
        if index < 0 or index >= doc.page_count:
            raise ValueError("페이지 번호가 올바르지 않습니다.")
        if req.get("thumb"):
            pix = doc.render_thumbnail_pixmap(index, _THUMB_WIDTH)
        else:
            zoom = float(req.get("zoom") or 1)
            zoom = min(_MAX_ZOOM, max(_MIN_ZOOM, zoom))
            pix = doc.render_page_pixmap(index, zoom)
        return opened, _png(pix)
    if op == "markups":
        if not opened:
            return opened, {"entries": []}
        entries = [
            {
                "pageIndex": entry.page_index,
                "text": entry.text,
                "kind": entry.kind,
                "rgb": [float(entry.rgb[0]), float(entry.rgb[1]), float(entry.rgb[2])],
            }
            for entry in doc.get_text_markup_entries()
        ]
        return opened, {"entries": entries}
    if op == "exportMarkups":
        _require_open(opened)
        entries = doc.get_text_markup_entries()
        if not entries:
            raise ValueError("저장할 형광펜·밑줄이 없습니다.")
        raw_path = str(req.get("path") or "").strip()
        if not raw_path:
            raise ValueError("저장 경로가 지정되지 않았습니다.")
        target = Path(raw_path).expanduser()
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        from pdf_editor.markup_export import export_markup_entries_to_xlsx

        export_markup_entries_to_xlsx(entries, target)
        return opened, {"path": str(target)}
    if op == "save":
        _require_open(opened)
        raw_path = str(req.get("path") or "").strip()
        saved = doc.save(raw_path or None)
        return True, {"doc": _summary(doc, True), "path": saved}
    if op == "insert":
        _require_open(opened)
        index = int(req.get("index") if req.get("index") is not None else doc.page_count)
        paths = [str(path) for path in (req.get("paths") or []) if str(path).strip()]
        if not paths:
            raise ValueError("추가할 파일이 없습니다.")
        added = doc.insert_files_at(index, paths)
        return True, {"doc": _summary(doc, True), "added": added}
    if op == "merge":
        paths = [str(path) for path in (req.get("paths") or []) if str(path).strip()]
        if len(paths) < 1:
            raise ValueError("병합할 파일이 없습니다.")
        doc.new_document()
        added = doc.insert_files_at(0, paths)
        return True, {"doc": _summary(doc, True), "added": added}
    if op == "mergeInspect":
        paths = [str(path) for path in (req.get("paths") or []) if str(path).strip()]
        return opened, {"items": _merge_inspect(paths, _str_map(req.get("passwords")))}
    if op == "mergeFiles":
        paths = [str(path) for path in (req.get("paths") or []) if str(path).strip()]
        if not paths:
            raise ValueError("병합할 파일이 없습니다.")
        output = str(req.get("output") or "").strip()
        if not output:
            raise ValueError("저장 경로가 지정되지 않았습니다.")
        try:
            result = _merge_files_to_path(paths, output, _str_map(req.get("passwords")))
        except PdfPasswordRequired as exc:
            return opened, {
                "needsPassword": True,
                "path": getattr(exc, "path", None),
                "rejected": isinstance(exc, PdfPasswordRejected),
            }
        return opened, result
    if op == "previewFile":
        return opened, _preview_file(
            str(req.get("path") or "").strip(),
            str(req.get("password")) if req.get("password") else None,
        )
    if op == "deletePages":
        _require_open(opened)
        indices = _indices(req)
        if not indices:
            raise ValueError("삭제할 페이지가 없습니다.")
        doc.delete_pages(indices)
        return True, {"doc": _summary(doc, True)}
    if op == "movePages":
        _require_open(opened)
        indices = _indices(req)
        if not indices:
            raise ValueError("이동할 페이지가 없습니다.")
        target = int(req.get("targetIndex") if req.get("targetIndex") is not None else 0)
        insert_at = doc.move_pages_to_index(indices, target)
        return True, {
            "doc": _summary(doc, True),
            "insertAt": insert_at,
            "count": len(indices),
        }
    if op == "insertBlank":
        _require_open(opened)
        index = int(req.get("index") if req.get("index") is not None else doc.page_count)
        doc.insert_blank_page_at(index)
        return True, {"doc": _summary(doc, True), "index": max(0, min(index, doc.page_count - 1))}
    if op == "rotatePages":
        _require_open(opened)
        indices = _indices(req)
        if not indices:
            indices = list(range(doc.page_count))
        degrees = int(req.get("degrees") or 90)
        doc.rotate_pages(indices, degrees)
        return True, {"doc": _summary(doc, True)}
    if op == "exportPagesPdf":
        _require_open(opened)
        indices = _indices(req)
        path = str(req.get("path") or "").strip()
        if not indices:
            raise ValueError("저장할 페이지를 선택하세요.")
        if not path:
            raise ValueError("저장 경로가 없습니다.")
        doc.export_pages_to_pdf(indices, path)
        return opened, {"path": path}
    if op == "exportPagesImages":
        _require_open(opened)
        indices = _indices(req)
        raw_dir = str(req.get("dir") or "").strip()
        if not indices:
            raise ValueError("저장할 페이지를 선택하세요.")
        if not raw_dir:
            raise ValueError("저장 폴더가 없습니다.")
        saved = doc.export_pages_as_images(
            indices,
            raw_dir,
            dpi=int(req.get("dpi") or 150),
            image_format=str(req.get("format") or "png"),
            jpeg_quality=int(req.get("jpegQuality") or 92),
            include_annotations=req.get("includeAnnotations") is not False,
        )
        return opened, {"dir": raw_dir, "files": [str(item) for item in saved]}
    if op == "textSelect":
        # 드래그 선택: 원본 PageCanvas 와 같은 단어 단위 선택 (줄 단위로 이어짐).
        _require_open(opened)
        index = int(req.get("index") or 0)
        shown = doc.get_page_rect(index)
        page_rect, rects, text, _selected = doc.get_text_block_selection(
            index,
            _markup_point(req["anchor"], shown),
            _markup_point(req["cursor"], shown),
            1.0,
        )
        if page_rect is None or not text.strip():
            return True, {"text": "", "rects": []}
        # 결과 사각형도 0..1 비율로 돌려줘서 화면 이미지 크기에 그대로 맞춘다.
        return True, {
            "text": text,
            "rects": [
                [
                    (x - shown.x0) / shown.width,
                    (y - shown.y0) / shown.height,
                    (x + w - shown.x0) / shown.width,
                    (y + h - shown.y0) / shown.height,
                ]
                for x, y, w, h in rects
            ],
        }
    if op == "markupAdd":
        # 선택 영역에 형광펜(highlight) 또는 밑줄(underline) 추가.
        _require_open(opened)
        index = int(req.get("index") or 0)
        kind = str(req.get("kind") or "highlight")
        color = _markup_rgb(req["color"])
        shown = doc.get_page_rect(index)
        page_rect, _rects, _text, selected = doc.get_text_block_selection(
            index,
            _markup_point(req["anchor"], shown),
            _markup_point(req["cursor"], shown),
            1.0,
        )
        applied = False
        if page_rect is not None and selected:
            if kind == "underline":
                applied = doc.add_text_underline(index, page_rect, color, selected_words=selected)
            else:
                applied = doc.add_text_highlight(index, page_rect, color, selected_words=selected)
        return True, {"doc": _summary(doc, True), "applied": bool(applied)}
    if op == "markupRemove":
        # 클릭한 위치의 형광펜 또는 밑줄 삭제 (형광펜 우선, 원본 _remove_*_selection 순서와 같다).
        _require_open(opened)
        index = int(req.get("index") or 0)
        point = _markup_point(req["point"], doc.get_page_rect(index))
        removed = False
        highlight_rect = doc.find_text_highlight_at_point(index, point)
        if highlight_rect is not None:
            removed = doc.remove_text_highlights_in_rect(index, highlight_rect)
        if not removed:
            underline_sel = doc.get_text_underline_selection_at_point(index, point)
            if underline_sel is not None:
                removed = doc.remove_text_underlines_in_rect(index, underline_sel[0])
        return True, {"doc": _summary(doc, True), "removed": bool(removed)}
    if op == "undo":
        _require_open(opened)
        changed = doc.undo()
        return True, {"doc": _summary(doc, True), "changed": changed}
    if op == "redo":
        _require_open(opened)
        changed = doc.redo()
        return True, {"doc": _summary(doc, True), "changed": changed}
    if op == "exportImagesTarget":
        # 원본 ExportImagesDialog 와 같이 "선택한 상위 폴더/문서명" 을 저장 폴더로 쓴다.
        # 이미 파일이 있는 폴더면 exists=True 로 알려서 덮어쓰기 확인을 하게 한다.
        _require_open(opened)
        parent = str(req.get("dir") or "").strip()
        if not parent:
            raise ValueError("저장 폴더가 없습니다.")
        target = Path(parent) / _export_folder_name(doc.display_name)
        exists = target.is_dir() and any(target.iterdir())
        return opened, {"dir": str(target), "exists": exists}
    if op == "exportImages":
        _require_open(opened)
        raw_dir = str(req.get("dir") or "").strip()
        if not raw_dir:
            raise ValueError("저장 폴더가 없습니다.")
        out = doc.export_document_as_images(
            raw_dir,
            dpi=int(req.get("dpi") or 150),
            image_format=str(req.get("format") or "png"),
            jpeg_quality=int(req.get("jpegQuality") or 92),
            page_from=int(req.get("pageFrom") or 1),
            page_to=int(req["pageTo"]) if req.get("pageTo") is not None else None,
            include_annotations=req.get("includeAnnotations") is not False,
        )
        return opened, {"dir": str(out)}
    if op == "search":
        _require_open(opened)
        query = str(req.get("query") or "")
        hits = [
            {
                "pageIndex": hit.page_index,
                "x0": float(hit.rect.x0),
                "y0": float(hit.rect.y0),
                "x1": float(hit.rect.x1),
                "y1": float(hit.rect.y1),
                "snippet": _search_snippet(doc, hit),
            }
            for hit in doc.search_text(query)
        ]
        return opened, {"hits": hits}
    if op == "extractPages":
        _require_open(opened)
        indices = _indices(req)
        if not indices:
            raise ValueError("복사할 페이지가 없습니다.")
        payload = doc.extract_pages_to_bytes(indices)
        return opened, {"pdf": base64.b64encode(payload).decode("ascii"), "count": len(indices)}
    if op == "insertPages":
        _require_open(opened)
        raw = str(req.get("pdf") or "").strip()
        if not raw:
            raise ValueError("붙여넣을 페이지가 없습니다.")
        index = int(req.get("index") if req.get("index") is not None else doc.page_count)
        added = doc.insert_pages_from_bytes(index, base64.b64decode(raw))
        return True, {"doc": _summary(doc, True), "added": added}
    if op == "cutPages":
        _require_open(opened)
        indices = _indices(req)
        if not indices:
            raise ValueError("잘라낼 페이지가 없습니다.")
        payload = doc.extract_pages_to_bytes(indices)
        doc.delete_pages(indices)
        return True, {
            "doc": _summary(doc, True),
            "pdf": base64.b64encode(payload).decode("ascii"),
            "count": len(indices),
        }
    if op == "reduceSize":
        _require_open(opened)
        options = OptimizeSizeOptions(
            image_dpi=int(req.get("dpi") or 150),
            image_quality_percent=int(req.get("quality") or 100),
            image_size_percent=int(req.get("sizePercent") or 100),
        )
        source = doc.save_to_bytes()
        payload = PdfDocument.build_optimized_payload(
            source,
            options,
            status_callback=_log,
            image_progress=_image_progress_logger(),
        )
        before, after = doc.apply_reduced_payload(payload)
        return True, {"doc": _summary(doc, True), "before": before, "after": after}
    if op == "pageNumberOptions":
        # 원본 PageNumberDialog 처럼, 이미 넣어 둔 쪽 번호 설정이 있으면 대화상자에 되살린다.
        _require_open(opened)
        applied = doc.load_applied_page_number_options()
        return True, {"options": _page_number_options_payload(applied) if applied is not None else None}
    if op == "pageNumbers":
        _require_open(opened)
        changed = doc.apply_page_numbers(_page_number_options(req.get("options")))
        return True, {"doc": _summary(doc, True), "changed": changed}
    if op == "ocr":
        _require_open(opened)
        from pdf_editor.ocr import ocr_ready, run_ocr_on_document

        if not ocr_ready():
            raise ValueError(
                "OCR 모델이 없습니다. 배포본을 다시 설치하거나, 개발 중이라면 "
                "ocr/models 에 공식 ONNX 파일을 두세요."
            )
        indices = _indices(req)
        if not indices:
            mode = str(req.get("mode") or "current")
            if mode == "all":
                indices = list(range(doc.page_count))
            else:
                indices = [int(req.get("index") or 0)]
        result = run_ocr_on_document(doc, indices, status_callback=_log)
        return True, {
            "doc": _summary(doc, True),
            "applied": result.applied,
            "skipped": result.skipped,
            "failed": result.failed,
            "lines": result.lines,
        }
    if op == "setPassword":
        _require_open(opened)
        password = str(req.get("password") or "")
        owner = req.get("ownerPassword")
        doc.set_password_protection(password, str(owner) if owner else None)
        return True, {"doc": _summary(doc, True)}
    if op == "clearPassword":
        _require_open(opened)
        doc.clear_password_protection()
        return True, {"doc": _summary(doc, True)}
    if op == "piiScan":
        _require_open(opened)
        from pdf_editor.pii_remove import scan_document_bytes

        raw_pages = req.get("pageIndices")
        page_indices = (
            [int(index) for index in raw_pages] if isinstance(raw_pages, list) else None
        )
        scanned = scan_document_bytes(
            doc.save_to_bytes(),
            page_indices=page_indices,
            status_callback=_log,
        )
        hits = [
            {
                "pageIndex": hit.page_index,
                "label": hit.label,
                "labelDisplay": hit.label_display,
                "text": hit.text,
                "rects": [[float(r.x0), float(r.y0), float(r.x1), float(r.y1)] for r in hit.rects],
                "hasGeometry": hit.has_geometry,
                "previewRects": _pii_preview_rects(doc, hit) if hit.has_geometry else [],
            }
            for hit in scanned.hits
        ]
        return opened, {
            "hits": hits,
            "pagesScanned": scanned.pages_scanned,
            "pagesWithoutText": scanned.pages_without_text,
            "locatableCount": scanned.locatable_count,
            "areaCount": scanned.area_count,
        }
    if op == "piiRedact":
        _require_open(opened)
        from pdf_editor.pii_remove import (
            DEFAULT_REDACT_STYLE,
            PiiHit,
            RedactStyle,
            redact_document_bytes,
        )

        try:
            style = RedactStyle(str(req.get("style") or ""))
        except ValueError:
            style = DEFAULT_REDACT_STYLE
        raw_hits = req.get("hits") or []
        hits = []
        for item in raw_hits:
            rects = tuple(fitz.Rect(*rect) for rect in (item.get("rects") or []))
            hits.append(
                PiiHit(
                    page_index=int(item.get("pageIndex") or 0),
                    label=str(item.get("label") or ""),
                    text=str(item.get("text") or ""),
                    rects=rects,
                )
            )
        payload, hit_count, area_count = redact_document_bytes(
            doc.save_to_bytes(), hits, style=style, status_callback=_log
        )
        doc.apply_reduced_payload(payload)
        return True, {
            "doc": _summary(doc, True),
            "hitCount": hit_count,
            "areaCount": area_count,
        }
    if op == "signaturePrepare":
        # 새 서명: 이미지를 다듬고 처음 놓을 위치를 정한다. PDF 는 아직 바꾸지 않는다(Enter 로 확정할 때 넣는다).
        _require_open(opened)
        page_index = int(req.get("pageIndex") or 0)
        raw = str(req.get("image") or "").strip()
        if not raw:
            raise ValueError("서명 이미지가 없습니다.")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        png, width, height = _prepare_signature(base64.b64decode(raw))
        page = doc.get_page_rect(page_index)
        rect = stamp_rect_from_memory(page, width, height, _stamp_memory["value"])
        return True, {
            "png": base64.b64encode(png).decode("ascii"),
            "width": width,
            "height": height,
            "rect": _rect_list(rect),
            "page": _page_box(page),
        }
    if op == "signatureFind":
        # 이미 넣은 서명 찾기. point 는 쪽 이미지 안의 0..1 비율 좌표.
        _require_open(opened)
        page_index = int(req.get("pageIndex") or 0)
        if not (0 <= page_index < doc.page_count):
            return True, {"hit": None}
        page = doc.get_page_rect(page_index)
        point = _markup_point(req["point"], page)
        hit = doc.find_signature_stamp_at(page_index, point)
        payload = _signature_hit_json(hit) if hit is not None else None
        if payload is not None:
            payload["page"] = _page_box(page)
        return True, {"hit": payload}
    if op == "signatureLift":
        # 기존 서명을 편집하려고 쪽에서 잠시 걷어낸다. 한 번의 실행 취소 단계가 생기고,
        # 취소(signatureCancel)하면 그 단계째로 되돌려 수정됨 표시도 남기지 않는다.
        _require_open(opened)
        hit = _signature_hit_from_json(req.get("hit"))
        before = doc.modified
        doc.delete_signature_stamp(hit, record_undo=True)
        _signature_lift["active"] = True
        _signature_lift["modified"] = before
        return True, {"doc": _summary(doc, True)}
    if op == "signatureCommit":
        _require_open(opened)
        page_index = int(req.get("pageIndex") or 0)
        raw = str(req.get("png") or "").strip()
        if not raw:
            raise ValueError("서명 이미지가 없습니다.")
        rect = _rect_from_list(req.get("rect"))
        lifted = bool(req.get("lifted")) and _signature_lift["active"]
        # 걷어낼 때 이미 실행 취소 단계를 만들었으니, 다시 놓을 때는 새로 만들지 않는다.
        doc.stamp_image(page_index, base64.b64decode(raw), rect, record_undo=not lifted)
        _signature_lift["active"] = False
        _stamp_memory["value"] = remember_stamp_placement(doc.get_page_rect(page_index), rect)
        return True, {"doc": _summary(doc, True)}
    if op == "signatureCancel":
        _require_open(opened)
        if _signature_lift["active"]:
            doc.revert_last_checkpoint(modified=bool(_signature_lift["modified"]))
            _signature_lift["active"] = False
        return True, {"doc": _summary(doc, True)}
    if op == "signatureDiscard":
        # 기존 서명을 걷어낸 뒤 삭제 확정(Esc 복원이 아니라 Delete). 이미 쪽에서 지워진 상태를 유지한다.
        _require_open(opened)
        _signature_lift["active"] = False
        return True, {"doc": _summary(doc, True)}
    if op == "hwpStatus":
        from pdf_editor.hwp_convert import hancom_installed

        return opened, {"installed": hancom_installed()}
    if op == "hwpConvert":
        from pdf_editor.hwp_convert import convert_hwp_to_pdf

        raw_path = str(req.get("path") or "").strip()
        if not raw_path:
            raise ValueError("HWP 파일 경로가 없습니다.")
        out_raw = str(req.get("output") or "").strip()
        output = Path(out_raw).expanduser() if out_raw else None
        result = convert_hwp_to_pdf(raw_path, output)
        return opened, {"path": str(result)}
    if op == "assocStatus":
        from pdf_editor.windows_file_assoc import is_pdf_association_registered, is_windows

        _apply_launcher(req)
        return opened, {"windows": is_windows(), "registered": is_pdf_association_registered()}
    if op == "assocRegister":
        from pdf_editor.windows_file_assoc import open_pdf_default_apps_settings, register_pdf_association

        _apply_launcher(req)
        register_pdf_association()
        if req.get("openSettings"):
            open_pdf_default_apps_settings()
        return opened, {"registered": True}
    if op == "assocUnregister":
        from pdf_editor.windows_file_assoc import unregister_pdf_association

        _apply_launcher(req)
        unregister_pdf_association()
        return opened, {"registered": False}
    if op == "pageRect":
        _require_open(opened)
        index = int(req.get("index") or 0)
        rect = doc.get_page_rect(index)
        return opened, {
            "x0": float(rect.x0),
            "y0": float(rect.y0),
            "x1": float(rect.x1),
            "y1": float(rect.y1),
            "width": float(rect.width),
            "height": float(rect.height),
        }
    raise ValueError(f"지원하지 않는 작업입니다: {op}")


def main() -> int:
    global _active_request_id
    configure_mupdf_messages()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    doc = PdfDocument()
    opened = False
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            req = json.loads(text)
        except json.JSONDecodeError:
            _write({"id": None, "ok": False, "error": "잘못된 JSON입니다."})
            continue
        request_id = req.get("id")
        _active_request_id = request_id
        try:
            opened, result = _handle(doc, opened, req)
            _write({"id": request_id, "ok": True, **result})
        except PdfPasswordRequired:
            _write(
                {
                    "id": request_id,
                    "ok": False,
                    "code": "password",
                    "error": "비밀번호가 필요합니다.",
                }
            )
        except PdfPasswordRejected:
            _write(
                {
                    "id": request_id,
                    "ok": False,
                    "code": "password_rejected",
                    "error": "비밀번호가 올바르지 않습니다.",
                }
            )
        except Exception as exc:
            _write({"id": request_id, "ok": False, "error": str(exc) or "처리하지 못했습니다."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
