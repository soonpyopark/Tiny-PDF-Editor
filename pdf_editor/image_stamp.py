"""이미지 넣기: 쪽 위에 올리는 이미지(표준 PDF 스탬프 주석) 의 순수 로직.

- 원본 이미지는 손대지 않고 보관하고, 보이는 모양(회전·반전·자르기·보정·배경 투명·투명도)은
  파라미터로만 저장한다. 그래서 언제든 다시 열어 고칠 수 있다(비파괴 편집).
- 이 모듈은 PDF 를 모른다. 파라미터 정리와 PIL/numpy 이미지 가공만 한다.
"""

from __future__ import annotations

import io
import json
from typing import Any

import numpy as np
from PIL import Image, ImageOps

# 이 앱이 넣은 스탬프 주석을 구분하는 제목(/T). 다른 프로그램이 만든 스탬프는 건드리지 않는다.
IMAGE_ANNOT_TITLE = "TinyPDF-Image"
# 주석 사전에 넣는 전용 키: 파라미터(JSON, 16진 문자열) / 원본 이미지 스트림 참조
KEY_PARAMS = "TinyImg"
KEY_ORIG = "TinyOrig"
PARAMS_VERSION = 1

# 원본으로 보관하는 이미지의 가장 긴 변(px). 더 크면 줄인다.
SOURCE_MAX_SIDE = 2400
# 화면 미리보기용 가장 긴 변(px)
PREVIEW_MAX_SIDE = 900

MIN_OPACITY = 5
MAX_CROP_TOTAL = 0.95  # 가로(세로)로 합쳐서 95% 까지만 자른다

_Image = Image.Image


def is_image_annot_title(title: Any) -> bool:
    return isinstance(title, str) and title == IMAGE_ANNOT_TITLE


# --------------------------------------------------------------------------- 파라미터


def default_params(original_size: tuple[int, int] = (1, 1)) -> dict[str, Any]:
    return {
        "v": PARAMS_VERSION,
        "ow": int(original_size[0]),
        "oh": int(original_size[1]),
        "bg": {"on": False, "color": [255, 255, 255], "tol": 20, "soft": 30},
        "op": 100,
        "rot": 0,
        "fx": False,
        "fy": False,
        "crop": [0.0, 0.0, 0.0, 0.0],
        "adj": {"bright": 0, "contrast": 0, "gray": False},
        "lock": False,
    }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _num(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _normalize_crop(raw: Any) -> list[float]:
    values = [0.0, 0.0, 0.0, 0.0]
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = [_clamp(_num(item, 0.0), 0.0, MAX_CROP_TOTAL) for item in raw]
    left, top, right, bottom = values
    if left + right > MAX_CROP_TOTAL:
        scale = MAX_CROP_TOTAL / (left + right)
        left, right = left * scale, right * scale
    if top + bottom > MAX_CROP_TOTAL:
        scale = MAX_CROP_TOTAL / (top + bottom)
        top, bottom = top * scale, bottom * scale
    return [round(left, 6), round(top, 6), round(right, 6), round(bottom, 6)]


def normalize_params(raw: Any, original_size: tuple[int, int] | None = None) -> dict[str, Any]:
    """저장된/받은 값을 안전한 범위로 정리한다. 모르는 키는 버린다."""
    src = raw if isinstance(raw, dict) else {}
    base = default_params(original_size or (src.get("ow") or 1, src.get("oh") or 1))
    bg_raw = src.get("bg") if isinstance(src.get("bg"), dict) else {}
    color_raw = bg_raw.get("color")
    if isinstance(color_raw, (list, tuple)) and len(color_raw) >= 3:
        color = [int(_clamp(_num(item, 255), 0, 255)) for item in color_raw[:3]]
    else:
        color = [255, 255, 255]
    adj_raw = src.get("adj") if isinstance(src.get("adj"), dict) else {}
    rot = int(_num(src.get("rot"), 0)) % 360
    rot = (rot // 90) * 90
    base.update(
        {
            "ow": max(1, int(_num(src.get("ow"), base["ow"]))),
            "oh": max(1, int(_num(src.get("oh"), base["oh"]))),
            "bg": {
                "on": bool(bg_raw.get("on", False)),
                "color": color,
                "tol": int(_clamp(_num(bg_raw.get("tol"), 20), 0, 100)),
                "soft": int(_clamp(_num(bg_raw.get("soft"), 30), 0, 100)),
            },
            "op": int(_clamp(_num(src.get("op"), 100), MIN_OPACITY, 100)),
            "rot": rot,
            "fx": bool(src.get("fx", False)),
            "fy": bool(src.get("fy", False)),
            "crop": _normalize_crop(src.get("crop")),
            "adj": {
                "bright": int(_clamp(_num(adj_raw.get("bright"), 0), -100, 100)),
                "contrast": int(_clamp(_num(adj_raw.get("contrast"), 0), -100, 100)),
                "gray": bool(adj_raw.get("gray", False)),
            },
            "lock": bool(src.get("lock", False)),
        }
    )
    return base


def rotate_crop(crop: list[float], clockwise: bool) -> list[float]:
    """보이는 이미지를 90도 돌릴 때 자르기 값(좌,상,우,하)도 같이 돌린다."""
    left, top, right, bottom = crop
    if clockwise:
        return [bottom, left, top, right]
    return [top, right, bottom, left]


def apply_patch(params: dict[str, Any], patch: Any) -> dict[str, Any]:
    """UI 가 보낸 변경 한 번을 합친다.

    patch 키: bg / adj (부분 갱신), op, crop, lock, rotate(+90|-90), flip('x'|'y'), cropReset.
    회전·반전은 '화면에 보이는 이미지 기준'으로 동작하고 자르기 값도 같이 바뀐다.
    """
    current = normalize_params(params)
    if not isinstance(patch, dict):
        return current
    out = json.loads(json.dumps(current))
    if isinstance(patch.get("bg"), dict):
        out["bg"].update(patch["bg"])
    if isinstance(patch.get("adj"), dict):
        out["adj"].update(patch["adj"])
    for key in ("op", "lock"):
        if key in patch:
            out[key] = patch[key]
    if "crop" in patch:
        out["crop"] = patch["crop"]
    if patch.get("cropReset"):
        out["crop"] = [0.0, 0.0, 0.0, 0.0]
    step = patch.get("rotate")
    if step in (90, -90, 270):
        clockwise = step == 90
        out["rot"] = (int(out["rot"]) + (90 if clockwise else -90)) % 360
        # 회전한 뒤 반전하는 순서이므로, 90도 돌리면 가로/세로 반전이 서로 바뀐다.
        out["fx"], out["fy"] = out["fy"], out["fx"]
        out["crop"] = rotate_crop(_normalize_crop(out["crop"]), clockwise)
    flip = patch.get("flip")
    if flip == "x":
        out["fx"] = not out["fx"]
        left, top, right, bottom = _normalize_crop(out["crop"])
        out["crop"] = [right, top, left, bottom]
    elif flip == "y":
        out["fy"] = not out["fy"]
        left, top, right, bottom = _normalize_crop(out["crop"])
        out["crop"] = [left, bottom, right, top]
    return normalize_params(out)


def transformed_size(params: dict[str, Any]) -> tuple[int, int]:
    """회전을 반영한 원본 크기(자르기 전)."""
    width, height = int(params["ow"]), int(params["oh"])
    if int(params["rot"]) in (90, 270):
        width, height = height, width
    return width, height


def natural_aspect(params: dict[str, Any]) -> float:
    """자르기까지 반영한 보이는 이미지의 가로/세로 비."""
    width, height = transformed_size(params)
    left, top, right, bottom = params["crop"]
    visible_w = max(1e-6, width * (1.0 - left - right))
    visible_h = max(1e-6, height * (1.0 - top - bottom))
    return visible_w / visible_h


def dump_params(params: dict[str, Any]) -> str:
    return json.dumps(params, separators=(",", ":"), ensure_ascii=True)


def load_params(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return normalize_params(json.loads(text))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- 원본 이미지


def normalize_source(data: bytes) -> tuple[bytes, str, int, int]:
    """넣을 이미지를 보관용 원본으로 정리한다: 방향(EXIF) 보정, 너무 큰 그림 축소, PNG/JPEG 로 통일.

    서명과 달리 흰 배경을 지우거나 여백을 자르지 않는다. 반환: (바이트, mime, 가로 px, 세로 px)
    """
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("이미지를 읽지 못했습니다.") from exc
    with src:
        was_jpeg = (src.format or "").upper() == "JPEG"
        try:
            rotated_by_exif = int(src.getexif().get(0x0112, 1) or 1) != 1
        except Exception:  # noqa: BLE001
            rotated_by_exif = False
        image = ImageOps.exif_transpose(src) if rotated_by_exif else src
        changed = rotated_by_exif
        if max(image.size) > SOURCE_MAX_SIDE:
            image = image.copy()
            image.thumbnail((SOURCE_MAX_SIDE, SOURCE_MAX_SIDE), Image.LANCZOS)
            changed = True
        if image.width < 2 or image.height < 2:
            raise ValueError("이미지가 너무 작습니다.")
        has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
        if has_alpha:
            rgba = image.convert("RGBA")
            if rgba.getchannel("A").getextrema()[0] >= 255:
                has_alpha = False
                image = rgba.convert("RGB")
            else:
                image = rgba
        elif image.mode != "RGB":
            image = image.convert("RGB")
        width, height = image.size
        buf = io.BytesIO()
        if has_alpha:
            image.save(buf, format="PNG")
            return buf.getvalue(), "image/png", int(width), int(height)
        if was_jpeg:
            if not changed:
                return bytes(data), "image/jpeg", int(width), int(height)
            image.save(buf, format="JPEG", quality=92)
            return buf.getvalue(), "image/jpeg", int(width), int(height)
        image.save(buf, format="PNG")
        return buf.getvalue(), "image/png", int(width), int(height)


def _open_rgba(data: bytes) -> tuple[_Image, bool]:
    with Image.open(io.BytesIO(data)) as src:
        is_jpeg = (src.format or "").upper() == "JPEG"
        return src.convert("RGBA"), is_jpeg


# --------------------------------------------------------------------------- 가공


def _adjust(rgb: np.ndarray, adj: dict[str, Any]) -> np.ndarray:
    bright = float(adj.get("bright", 0))
    contrast = float(adj.get("contrast", 0))
    gray = bool(adj.get("gray", False))
    if not bright and not contrast and not gray:
        return rgb
    out = rgb.astype(np.float32)
    if gray:
        luma = out[:, :, 0] * 0.299 + out[:, :, 1] * 0.587 + out[:, :, 2] * 0.114
        out = np.repeat(luma[:, :, None], 3, axis=2)
    if contrast:
        c = contrast * 2.55
        factor = (259.0 * (c + 255.0)) / (255.0 * (259.0 - c))
        out = factor * (out - 128.0) + 128.0
    if bright:
        out = out + bright * 2.55
    return np.clip(out, 0, 255).astype(np.uint8)


def knockout_color(rgba: np.ndarray, color: list[int], tol: int, soft: int) -> np.ndarray:
    """color(기본 흰색)에 가까운 픽셀을 투명하게 한다.

    tol: 이 거리 안은 완전 투명(0~100), soft: 그 바깥으로 이만큼 서서히 불투명해짐(0~100).
    가장자리의 반투명 픽셀은 color 위에 겹쳐 있었다고 보고 색을 되돌려(흰 테두리 방지) 쓴다.
    """
    out = np.array(rgba, copy=True)
    rgb = out[:, :, :3].astype(np.float32)
    key = np.array(color[:3], dtype=np.float32)
    dist = np.abs(rgb - key).max(axis=2)
    threshold = tol * 1.6
    width = soft * 0.64
    if width <= 0.0:
        keep = (dist > threshold).astype(np.float32)
    else:
        keep = np.clip((dist - threshold) / width, 0.0, 1.0)
    partial = (keep > 0.0) & (keep < 1.0)
    if np.any(partial):
        safe = np.where(keep > 0.0, keep, 1.0)[:, :, None]
        restored = np.clip(key + (rgb - key) / safe, 0, 255)
        rgb = np.where(partial[:, :, None], restored, rgb)
    out[:, :, :3] = rgb.astype(np.uint8)
    out[:, :, 3] = np.clip(out[:, :, 3].astype(np.float32) * keep, 0, 255).astype(np.uint8)
    return out


def _transform(img: _Image, params: dict[str, Any]) -> _Image:
    """회전 → 반전(보이는 기준) → 색 보정 → 배경 투명. 자르기/투명도/쪽 회전 보정은 하지 않는다."""
    rot = int(params["rot"])
    if rot == 90:
        img = img.transpose(Image.Transpose.ROTATE_270)  # 시계방향 90
    elif rot == 180:
        img = img.transpose(Image.Transpose.ROTATE_180)
    elif rot == 270:
        img = img.transpose(Image.Transpose.ROTATE_90)
    if params["fx"]:
        img = ImageOps.mirror(img)
    if params["fy"]:
        img = ImageOps.flip(img)
    arr = np.array(img.convert("RGBA"))
    adj = params["adj"]
    if adj["bright"] or adj["contrast"] or adj["gray"]:
        arr[:, :, :3] = _adjust(arr[:, :, :3], adj)
    bg = params["bg"]
    if bg["on"]:
        arr = knockout_color(arr, bg["color"], bg["tol"], bg["soft"])
    return Image.fromarray(arr, "RGBA")


def _crop(img: _Image, crop: list[float]) -> _Image:
    left, top, right, bottom = crop
    if not (left or top or right or bottom):
        return img
    width, height = img.size
    x0 = int(round(width * left))
    y0 = int(round(height * top))
    x1 = int(round(width * (1.0 - right)))
    y1 = int(round(height * (1.0 - bottom)))
    x1 = max(x1, x0 + 1)
    y1 = max(y1, y0 + 1)
    return img.crop((x0, y0, min(width, x1), min(height, y1)))


def preview_png(source: bytes, params: dict[str, Any], max_side: int = PREVIEW_MAX_SIDE) -> tuple[bytes, int, int]:
    """화면 미리보기: 자르기 전의 가공 결과(PNG). 자르기·투명도는 화면(CSS)이 입힌다.

    반환: (PNG 바이트, 가공 결과의 전체 가로, 세로 — 미리보기를 줄이기 전 크기)
    """
    params = normalize_params(params)
    img, _is_jpeg = _open_rgba(source)
    full_w, full_h = img.size
    scale = min(1.0, max_side / max(full_w, full_h))
    if scale < 1.0:
        img = img.resize((max(1, round(full_w * scale)), max(1, round(full_h * scale))), Image.LANCZOS)
    out = _transform(img, params)
    tw, th = transformed_size(params)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), tw, th


def final_image(source: bytes, params: dict[str, Any], page_rotation: int = 0) -> tuple[bytes, str]:
    """PDF 에 넣을 최종 이미지. 쪽이 회전돼 있어도 화면에서 똑바로 보이도록 미리 반대로 돌려 둔다.

    반환: (바이트, mime)
    """
    params = normalize_params(params)
    img, source_is_jpeg = _open_rgba(source)
    out = _transform(img, params)
    out = _crop(out, params["crop"])
    opacity = int(params["op"])
    if opacity < 100:
        arr = np.array(out)
        arr[:, :, 3] = np.clip(arr[:, :, 3].astype(np.float32) * (opacity / 100.0), 0, 255).astype(np.uint8)
        out = Image.fromarray(arr, "RGBA")
    rotation = int(page_rotation or 0) % 360
    if rotation:
        # 쪽이 시계방향으로 `rotation` 도 돌아 보이므로, 그림은 반시계방향으로 미리 돌려 놓는다.
        out = out.rotate(rotation, expand=True)
    has_alpha = out.getchannel("A").getextrema()[0] < 255
    buf = io.BytesIO()
    if has_alpha:
        out.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    rgb = out.convert("RGB")
    untouched = (
        source_is_jpeg
        and not rotation
        and params["rot"] == 0
        and not params["fx"]
        and not params["fy"]
        and params["crop"] == [0.0, 0.0, 0.0, 0.0]
        and not params["bg"]["on"]
        and not params["adj"]["bright"]
        and not params["adj"]["contrast"]
        and not params["adj"]["gray"]
    )
    if untouched:
        return bytes(source), "image/jpeg"
    if source_is_jpeg:
        rgb.save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    rgb.save(buf, format="PNG")
    return buf.getvalue(), "image/png"
