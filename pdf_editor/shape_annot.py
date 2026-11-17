"""그리기 도형: 선·화살표·직사각형·타원형·다각형·클라우드·폴리라인·텍스트 상자.

모두 표준 PDF 주석(Line / Square / Circle / Polygon / PolyLine / FreeText)으로 넣는다.
다른 PDF 프로그램에서도 그대로 보이고 고칠 수 있다. 제목(/T)이 SHAPE_ANNOT_TITLE 인 것만 이 앱이 다시 편집한다.

- 모양(색·굵기·글자 …)은 주석 사전의 전용 키(KEY_PARAMS)에 JSON(16진 문자열)으로 보관한다.
- 위치(좌표)는 주석 자체에서 읽는다. 그래서 다른 프로그램이 옮기거나 쪽을 돌려도 따라간다.
- 좌표는 화면(view, 회전 반영) 기준 pt 로 주고받고, 주석 안에서는 회전 전 쪽 좌표(derotation_matrix)로 쓴다.
- 고칠 때는 주석을 새로 만든다(id 가 바뀐다). 이미지 넣기와 같은 방식이다.
"""

from __future__ import annotations

import html
import json
import math
import re
from typing import Any

import pymupdf as fitz

SHAPE_ANNOT_TITLE = "TinyPDF-Shape"
KEY_PARAMS = "TinyShape"
PARAMS_VERSION = 1

POINT_KINDS = {"line": 2, "arrow": 2, "polygon": 3, "cloud": 3, "polyline": 2}
RECT_KINDS = ("rect", "ellipse", "text")
KINDS = tuple(POINT_KINDS) + RECT_KINDS
MAX_POINTS = 400
MIN_SIZE = 1.0  # pt. 이보다 작은 도형은 만들지 않는다.

DEFAULT_COLOR = "#dc2626"
# 텍스트 상자 안쪽 여백(pt). 글은 여백 + 테두리 굵기의 2배만큼 안쪽에서 시작한다. (화면 입력창 여백과 맞춘 값)
TEXT_MARGIN = 4.0
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
_RC_HEAD = (
    '<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" xfa:contentType="text/html" '
    'xfa:APIVersion="Acrobat:8.0.0" xfa:spec="2.4">'
)
_STROKE_OP_RE = re.compile(rb"(?m)^[0-9.\-+eE ]+ RG$")


def is_shape_annot_title(title: Any) -> bool:
    return isinstance(title, str) and title == SHAPE_ANNOT_TITLE


# --------------------------------------------------------------------------- 파라미터


def clean_hex(value: Any, default: str | None) -> str | None:
    if isinstance(value, str):
        match = _HEX_RE.match(value.strip())
        if match:
            digits = match.group(1).lower()
            if len(digits) == 3:
                digits = "".join(ch * 2 for ch in digits)
            return "#" + digits
    return default


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    digits = value.lstrip("#")
    return tuple(int(digits[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _num(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def default_params(kind: str) -> dict[str, Any]:
    is_text = kind == "text"
    return {
        "v": PARAMS_VERSION,
        "kind": kind,
        "color": DEFAULT_COLOR if not is_text else "#000000",
        "fill": None,
        "width": 0.0 if is_text else 2.0,
        "opacity": 1.0,
        "dash": False,
        "text": "",
        "fontSize": 14.0,
        "textColor": "#000000",
        "align": 0,
    }


def normalize_params(raw: Any, kind: str | None = None) -> dict[str, Any]:
    """모르는 값은 기본값으로, 범위를 벗어난 값은 범위 안으로 고친다."""
    raw = raw if isinstance(raw, dict) else {}
    kind = kind or raw.get("kind")
    if kind not in KINDS:
        raise ValueError("알 수 없는 도형입니다.")
    base = default_params(kind)
    is_text = kind == "text"
    out = dict(base)
    out["color"] = clean_hex(raw.get("color"), base["color"])
    out["fill"] = clean_hex(raw.get("fill"), None) if kind in ("rect", "ellipse", "polygon", "cloud", "text") else None
    low = 0.0 if is_text else 0.25
    out["width"] = round(_num(raw.get("width"), base["width"], low, 40.0), 2)
    out["opacity"] = round(_num(raw.get("opacity"), 1.0, 0.05, 1.0), 3)
    out["dash"] = bool(raw.get("dash")) and not is_text
    text = raw.get("text")
    out["text"] = (str(text) if text is not None else "")[:5000] if is_text else ""
    out["fontSize"] = round(_num(raw.get("fontSize"), 14.0, 4.0, 200.0), 1)
    out["textColor"] = clean_hex(raw.get("textColor"), "#000000")
    align = raw.get("align")
    out["align"] = int(align) if align in (0, 1, 2) else 0
    return out


def dump_params(params: dict[str, Any]) -> str:
    return json.dumps(params, separators=(",", ":"), ensure_ascii=True)


def load_params(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        raw = json.loads(text)
        return normalize_params(raw, raw.get("kind") if isinstance(raw, dict) else None)
    except (ValueError, TypeError, AttributeError):
        return None


def params_hex(params: dict[str, Any]) -> str:
    return "<" + dump_params(params).encode("ascii").hex() + ">"


# --------------------------------------------------------------------------- 도형 좌표


def clean_points(raw: Any, kind: str) -> list[list[float]]:
    """화면 좌표 점 목록 정리. 겹친 점은 하나로 줄이고, 개수가 모자라면 오류."""
    need = POINT_KINDS[kind]
    points: list[list[float]] = []
    for item in raw or []:
        try:
            x, y = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        if points and abs(points[-1][0] - x) < 0.01 and abs(points[-1][1] - y) < 0.01:
            continue
        points.append([round(x, 3), round(y, 3)])
        if len(points) >= MAX_POINTS:
            break
    if kind in ("line", "arrow"):
        points = points[:2]
    if len(points) < need:
        raise ValueError("도형의 점이 모자랍니다.")
    if kind in ("polygon", "cloud") and len(points) > 3 and points[0] == points[-1]:
        points.pop()
    return points


def clean_rect(raw: Any) -> fitz.Rect:
    try:
        rect = fitz.Rect([float(v) for v in raw])
    except (TypeError, ValueError):
        raise ValueError("도형 위치가 올바르지 않습니다.") from None
    rect.normalize()
    if (
        not all(math.isfinite(v) for v in tuple(rect))
        or rect.width < MIN_SIZE
        or rect.height < MIN_SIZE
    ):
        raise ValueError("도형이 너무 작습니다.")
    return rect


def same_geom(a: dict[str, Any], b: dict[str, Any], eps: float = 0.02) -> bool:
    if "rect" in a and "rect" in b:
        return all(abs(x - y) <= eps for x, y in zip(a["rect"], b["rect"]))
    pa, pb = a.get("points"), b.get("points")
    if pa is None or pb is None or len(pa) != len(pb):
        return False
    return all(abs(p[0] - q[0]) <= eps and abs(p[1] - q[1]) <= eps for p, q in zip(pa, pb))


def clean_geom(kind: str, geom: Any) -> dict[str, Any]:
    """{points} 또는 {rect} 로 정리. kind 에 맞지 않는 쪽은 버린다."""
    geom = geom if isinstance(geom, dict) else {}
    if kind in POINT_KINDS:
        return {"points": clean_points(geom.get("points"), kind)}
    rect = clean_rect(geom.get("rect"))
    return {"rect": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]}


# --------------------------------------------------------------------------- 주석 만들기


def _text_rc(params: dict[str, Any]) -> str:
    lines = str(params["text"]).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body = "<br/>".join(html.escape(line, quote=False) for line in lines)
    align = {0: "left", 1: "center", 2: "right"}[params["align"]]
    style = (
        f"margin:{TEXT_MARGIN:g}pt;font-size:{params['fontSize']:g}pt;color:{params['textColor']};"
        f"font-family:sans-serif;text-align:{align}"
    )
    return f'{_RC_HEAD}<p style="{style}">{body}</p></body>'


def _paint_border_color(doc: fitz.Document, annot, color: str) -> None:
    """텍스트 상자 테두리 색. MuPDF 는 풍부한 글 모드에서 테두리를 검정으로만 그려서 모양 스트림을 직접 고친다."""
    kind, value = doc.xref_get_key(annot.xref, "AP/N")
    if kind != "xref":
        return
    ap_xref = int(str(value).split()[0])
    stream = doc.xref_stream(ap_xref)
    if not stream:
        return
    r, g, b = hex_to_rgb(color)
    code = f"{r:g} {g:g} {b:g} RG".encode("ascii")
    patched, count = _STROKE_OP_RE.subn(code, bytes(stream), count=1)
    if count:
        doc.update_stream(ap_xref, patched, new=False, compress=False)


def _dashes(width: float) -> list[int]:
    # PyMuPDF 는 점선 간격을 정수로만 받는다.
    unit = max(1.0, width)
    return [max(1, round(unit * 3)), max(1, round(unit * 2))]


def build_annot(page, kind: str, geom: dict[str, Any], params: dict[str, Any]) -> int:
    """주석 하나를 만든다. geom 은 clean_geom 결과(화면 좌표). 반환: xref."""
    doc = page.parent
    der = page.derotation_matrix
    width = float(params["width"])
    stroke = hex_to_rgb(params["color"])
    fill = hex_to_rgb(params["fill"]) if params["fill"] else None

    if kind in POINT_KINDS:
        pts = [fitz.Point(x, y) * der for x, y in geom["points"]]
        if kind in ("line", "arrow"):
            annot = page.add_line_annot(pts[0], pts[1])
            if kind == "arrow":
                annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
        elif kind == "polyline":
            annot = page.add_polyline_annot(pts)
        else:
            annot = page.add_polygon_annot(pts)
    else:
        rect = fitz.Rect(geom["rect"]) * der
        rect.normalize()
        if kind == "rect":
            annot = page.add_rect_annot(rect)
        elif kind == "ellipse":
            annot = page.add_circle_annot(rect)
        else:
            annot = _build_text_annot(page, rect, params)

    xref = int(annot.xref)
    annot.set_info(title=SHAPE_ANNOT_TITLE, content=params["text"] if kind == "text" else "도형")
    if kind != "text":
        if kind == "arrow":
            fill_color = stroke  # 화살촉 안쪽
        else:
            fill_color = fill if kind in ("rect", "ellipse", "polygon", "cloud") else None
        annot.set_colors(stroke=stroke, fill=fill_color)
        dashes = _dashes(width) if params["dash"] else None
        if kind == "cloud":
            annot.set_border(width=width, dashes=dashes, clouds=1)
        else:
            annot.set_border(width=width, dashes=dashes)
        annot.set_opacity(float(params["opacity"]))
        annot.update()
    annot.set_flags(fitz.PDF_ANNOT_IS_PRINT)
    doc.xref_set_key(xref, KEY_PARAMS, params_hex(params))
    return xref


def _build_text_annot(page, rect: fitz.Rect, params: dict[str, Any]):
    doc = page.parent
    fill = hex_to_rgb(params["fill"]) if params["fill"] else None
    annot = page.add_freetext_annot(
        rect,
        "x",
        fontsize=float(params["fontSize"]),
        text_color=hex_to_rgb(params["textColor"]),
        fill_color=fill,
        border_width=float(params["width"]),
        dashes=None,
        opacity=float(params["opacity"]),
        align=int(params["align"]),
        rotate=int(page.rotation or 0),
    )
    # 일반 모드는 한글 글자 사이가 벌어져 보이므로, 같은 주석에 서식 있는 글(RC)을 넣고 모양을 다시 만든다.
    doc.xref_set_key(annot.xref, "RC", fitz.get_pdf_str(_text_rc(params)))
    annot.update(opacity=float(params["opacity"]))
    if float(params["width"]) > 0:
        _paint_border_color(doc, annot, params["color"])
    return annot


# --------------------------------------------------------------------------- 읽기


def read_geom(page, annot, params: dict[str, Any]) -> dict[str, Any]:
    """주석에서 화면 좌표 모양을 읽는다."""
    kind = params["kind"]
    rot = page.rotation_matrix
    if kind in POINT_KINDS:
        verts = annot.vertices or []
        points = [fitz.Point(v) * rot for v in verts]
        return {"points": [[round(float(p.x), 3), round(float(p.y), 3)] for p in points]}
    rect = fitz.Rect(annot.rect) * rot
    rect.normalize()
    # 주석 상자는 테두리 반 굵기만큼 바깥으로 커진다. 그린 모양 자체의 상자로 돌려놓는다.
    half = max(0.0, float(annot.border.get("width", 0) or 0)) / 2.0
    if half > 0 and rect.width > 2 * half and rect.height > 2 * half:
        rect = fitz.Rect(rect.x0 + half, rect.y0 + half, rect.x1 - half, rect.y1 - half)
    return {"rect": [round(float(v), 3) for v in tuple(rect)]}
