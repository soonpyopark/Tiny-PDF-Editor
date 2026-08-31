#!/usr/bin/env python3
"""Tiny PDF Editor OCR worker. RapidOCR (ONNX) first, PaddleOCR if present."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny PDF Editor OCR helper")
    parser.add_argument("--image", required=True, help="Input page image")
    parser.add_argument("--output", required=True, help="JSON output path")
    parser.add_argument("--ocr-dir", default="", help="OCR pack folder")
    parser.add_argument(
        "--lang",
        default="korean",
        help="korean, en, ko+en, or ko+en+ch",
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="OCR a cropped text-line strip (no page upscale)",
    )
    return parser.parse_args()


def _box_bounds(box) -> tuple[float, float, float, float] | None:
    try:
        if hasattr(box, "tolist"):
            box = box.tolist()
        if (
            isinstance(box, (list, tuple))
            and len(box) == 4
            and all(isinstance(value, (int, float)) for value in box)
        ):
            x0, y0, x1, y1 = (float(value) for value in box)
            return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _items_from_legacy_ocr(result) -> list[dict]:
    items: list[dict] = []
    pages = result if isinstance(result, list) else []
    if pages and pages[0] is None:
        return items
    lines = pages[0] if pages and isinstance(pages[0], list) else pages
    for line in lines or []:
        if not line or len(line) < 2:
            continue
        box, payload = line[0], line[1]
        if isinstance(payload, (list, tuple)) and payload:
            text = str(payload[0] or "").strip()
            conf = float(payload[1]) if len(payload) > 1 else 0.0
        else:
            text = str(payload or "").strip()
            conf = 0.0
        bounds = _box_bounds(box)
        if not text or bounds is None:
            continue
        x0, y0, x1, y1 = bounds
        items.append(
            {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "conf": conf}
        )
    return items


def _items_from_predict(result) -> list[dict]:
    items: list[dict] = []
    rows = result if isinstance(result, list) else [result]
    for row in rows:
        if row is None:
            continue
        if isinstance(row, dict):
            texts = row.get("rec_texts") or row.get("rec_text") or []
            scores = row.get("rec_scores") or row.get("rec_score") or []
            boxes = row.get("rec_boxes") or row.get("dt_polys") or row.get("rec_polys") or []
        else:
            texts = getattr(row, "rec_texts", None) or getattr(row, "rec_text", []) or []
            scores = getattr(row, "rec_scores", None) or []
            boxes = (
                getattr(row, "rec_boxes", None)
                or getattr(row, "dt_polys", None)
                or []
            )
        for index, text in enumerate(texts):
            value = str(text or "").strip()
            if not value:
                continue
            box = boxes[index] if index < len(boxes) else None
            bounds = _box_bounds(box) if box is not None else None
            if bounds is None:
                continue
            x0, y0, x1, y1 = bounds
            conf = float(scores[index]) if index < len(scores) else 0.0
            items.append(
                {"text": value, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "conf": conf}
            )
    return items


def _plausible_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 2:
        return False
    latin = [char for char in letters if char.isascii()]
    if len(latin) < 2 or len(latin) / len(letters) < 0.85:
        return False
    vowels = sum(1 for char in latin if char.lower() in "aeiou")
    return vowels >= 1 and vowels / len(latin) >= 0.15


def _plausible_hanja(text: str) -> bool:
    hanja = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    hangul = sum(1 for char in text if "\uac00" <= char <= "\ud7a3")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    visible = hanja + hangul + latin
    return hanja >= 2 and visible > 0 and hanja / visible >= 0.7


def _keep_ocr_text(text: str, conf: float) -> str:
    value = (text or "").strip()
    if not value or conf < 0.70:
        return ""
    hangul = sum(1 for char in value if "\uac00" <= char <= "\ud7a3")
    hanja = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in value if char.isascii() and char.isalpha())
    compact = "".join(value.split())
    if "/" in compact or "%" in compact:
        digits = sum(1 for char in compact if char.isdigit())
        if digits >= 2 and hangul < 4 and hanja < 2 and latin < 4:
            return ""
    if hangul >= 2 or hanja >= 1:
        return value
    compact_marks = set("『』「」\"'“”‘’")
    if value and all(char in compact_marks for char in value):
        return value
    if 1 <= len(value) <= 3 and any(char.isascii() and char.isalpha() for char in value):
        if all(char.isascii() and (char.isalpha() or char in ".-'") for char in value):
            return value
    if _plausible_english(value) and conf >= 0.80:
        return value
    return ""


def _filter_kept_items(items: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for item in items:
        try:
            conf = float(item.get("conf") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        text = _keep_ocr_text(str(item.get("text") or ""), conf)
        if not text:
            continue
        kept.append({**item, "text": text, "conf": conf})
    return kept


def _items_from_rapid(result) -> list[dict]:
    if result is None:
        return []
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if texts is None:
        if isinstance(result, (list, tuple)):
            return _items_from_legacy_ocr([list(result)])
        return []
    items: list[dict] = []
    for index, text in enumerate(texts):
        value = str(text or "").strip()
        if not value:
            continue
        box = boxes[index] if boxes is not None and index < len(boxes) else None
        bounds = _box_bounds(box) if box is not None else None
        if bounds is None:
            continue
        x0, y0, x1, y1 = bounds
        conf = float(scores[index]) if scores is not None and index < len(scores) else 0.0
        items.append(
            {"text": value, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "conf": conf}
        )
    return items


def _first_dir(models: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = models / name
        if path.is_dir():
            return path
    return None


def _first_file(models: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = models / name
        if path.is_file():
            return path
    return None


def _model_kwargs(ocr_dir: Path) -> dict:
    models = ocr_dir / "models"
    kwargs: dict = {}
    mapping = {
        "det_model_dir": ("det", "ch_PP-OCRv4_det_infer", "PP-OCRv4_mobile_det"),
        "rec_model_dir": (
            "rec",
            "korean_PP-OCRv4_rec_infer",
            "korean_PP-OCRv4_mobile_rec",
        ),
        "cls_model_dir": ("cls", "ch_ppocr_mobile_v2.0_cls_infer"),
    }
    for key, names in mapping.items():
        found = _first_dir(models, names)
        if found is not None:
            kwargs[key] = str(found)
    return kwargs


def _rec_langs(lang: str) -> list[str]:
    key = (lang or "korean").strip().lower().replace("_", "+").replace(" ", "")
    aliases = {
        "ko+en": ["korean", "en", "ch"],
        "ko+en+ch": ["korean", "en", "ch"],
        "korean+en": ["korean", "en", "ch"],
        "korean+english": ["korean", "en", "ch"],
        "auto": ["korean", "en", "ch"],
        "default": ["korean", "en", "ch"],
        "korean": ["korean"],
        "ko": ["korean"],
        "kr": ["korean"],
        "en": ["en"],
        "eng": ["en"],
        "english": ["en"],
        "ch": ["ch"],
        "chinese": ["ch"],
        "hanja": ["ch"],
    }
    return aliases.get(key, [lang])


def _iou(a: dict, b: dict) -> float:
    ax0, ay0, ax1, ay1 = a["x0"], a["y0"], a["x1"], a["y1"]
    bx0, by0, bx1, by1 = b["x0"], b["y0"], b["x1"], b["y1"]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _has_cjk(text: str) -> bool:
    return any(
        "\uac00" <= char <= "\ud7a3" or "\u4e00" <= char <= "\u9fff"
        for char in text
    )


def _merge_items(groups: list[list[dict]], iou_thresh: float = 0.5) -> list[dict]:
    merged: list[dict] = []
    for group in groups:
        for item in group:
            best_index = -1
            best_iou = 0.0
            for index, existing in enumerate(merged):
                score = _iou(item, existing)
                if score > best_iou:
                    best_index = index
                    best_iou = score
            if best_index >= 0 and best_iou >= iou_thresh:
                if float(item.get("conf") or 0) > float(merged[best_index].get("conf") or 0):
                    merged[best_index] = item
            else:
                merged.append(item)
    return merged


def _merge_extra_script(
    base: list[dict],
    extra: list[dict],
    accept,
    iou_thresh: float = 0.5,
) -> list[dict]:
    """Add English/Hanja only where they do not overwrite Hangul/Hanja lines."""
    merged = list(base)
    for item in extra:
        text = str(item.get("text") or "").strip()
        if not accept(text):
            continue
        best_index = -1
        best_iou = 0.0
        for index, existing in enumerate(merged):
            score = _iou(item, existing)
            if score > best_iou:
                best_index = index
                best_iou = score
        if best_index >= 0 and best_iou >= iou_thresh:
            existing = str(merged[best_index].get("text") or "")
            short = len(text) <= 3 or _plausible_hanja(text)
            if _has_cjk(existing) and short and text not in existing:
                host = merged[best_index]
                try:
                    x0, x1 = float(host["x0"]), float(host["x1"])
                    mid = 0.5 * (float(item["x0"]) + float(item["x1"]))
                    index = int(round((mid - x0) / max(1.0, x1 - x0) * len(existing)))
                    index = max(0, min(len(existing), index))
                    host["text"] = existing[:index] + text + existing[index:]
                except (KeyError, TypeError, ValueError):
                    pass
                continue
            if _has_cjk(existing) or _plausible_english(existing):
                continue
            merged[best_index] = item
        else:
            merged.append(item)
    return merged


def _prepare_image(image: Path) -> tuple[Path, float, Path | None]:
    from PIL import Image

    picture = Image.open(image).convert("RGB")
    long_side = max(picture.size)
    target = 2400
    if long_side >= target:
        return image, 1.0, None
    scale = min(target / long_side, 2.5)
    resized = picture.resize(
        (max(1, int(picture.width * scale)), max(1, int(picture.height * scale))),
        Image.Resampling.LANCZOS,
    )
    scaled = image.with_name(f"{image.stem}_ocrup.png")
    resized.save(scaled)
    return scaled, scale, scaled


def _scale_items(items: list[dict], scale: float) -> list[dict]:
    if scale == 1.0:
        return items
    scaled: list[dict] = []
    for item in items:
        scaled.append(
            {
                **item,
                "x0": float(item["x0"]) / scale,
                "y0": float(item["y0"]) / scale,
                "x1": float(item["x1"]) / scale,
                "y1": float(item["y1"]) / scale,
            }
        )
    return scaled


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _cluster_rows(items: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in sorted(items, key=lambda row: (row["y0"], row["x0"])):
        center = 0.5 * (float(item["y0"]) + float(item["y1"]))
        placed = False
        for row in rows:
            if row["y0"] <= center <= row["y1"]:
                row["items"].append(item)
                row["y0"] = min(row["y0"], float(item["y0"]))
                row["y1"] = max(row["y1"], float(item["y1"]))
                placed = True
                break
        if not placed:
            rows.append(
                {
                    "y0": float(item["y0"]),
                    "y1": float(item["y1"]),
                    "items": [item],
                }
            )
    return rows


def _merge_row_items(items: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for row in _cluster_rows(items):
        parts = sorted(row["items"], key=lambda item: float(item["x0"]))
        confs = [float(item.get("conf") or 0.0) for item in parts]
        merged.append(
            {
                "text": "".join(str(item.get("text") or "") for item in parts),
                "x0": min(float(item["x0"]) for item in parts),
                "y0": min(float(item["y0"]) for item in parts),
                "x1": max(float(item["x1"]) for item in parts),
                "y1": max(float(item["y1"]) for item in parts),
                "conf": sum(confs) / len(confs) if confs else 0.0,
            }
        )
    return merged


def _refill_missed_lines(
    image: Path,
    items: list[dict],
    ocr_dir: Path,
    rec_lang: str,
) -> list[dict]:
    """Re-OCR suspiciously large gaps between detected lines.

    Dense book pages sometimes skip a whole text line at the detection
    stage. The skipped line is still readable when cropped on its own.
    """
    if len(items) < 3:
        return items
    from PIL import Image

    rows = _cluster_rows(items)
    if len(rows) < 3:
        return items
    heights = [row["y1"] - row["y0"] for row in rows]
    gaps = [b["y0"] - a["y1"] for a, b in zip(rows, rows[1:]) if b["y0"] > a["y1"]]
    med_h = _median(heights)
    med_g = _median(gaps) if gaps else med_h * 0.35
    if med_h <= 0:
        return items
    threshold = max(med_h * 0.85, med_g * 1.8)
    picture = Image.open(image).convert("RGB")
    page_h = picture.height
    filled = list(items)
    strip_engine = None
    for previous, nxt in zip(rows, rows[1:]):
        gap = nxt["y0"] - previous["y1"]
        if gap < threshold or gap > med_h * 4:
            continue
        y0 = max(0, int(previous["y1"] - med_h * 0.1))
        y1 = min(page_h, int(nxt["y0"] + med_h * 0.1))
        if y1 - y0 < 8 or y0 > page_h * 0.92:
            continue
        if strip_engine is None:
            from rapidocr import RapidOCR

            strip_engine = RapidOCR(
                params=_rapid_engine_params(ocr_dir, rec_lang, strip=True)
            )
        crop_path = image.with_name(f"{image.stem}_gap{y0}.png")
        picture.crop((0, y0, picture.width, y1)).save(crop_path)
        try:
            extra = _items_from_rapid(
                strip_engine(str(crop_path), box_thresh=0.3, unclip_ratio=1.2)
            )
        except Exception:
            extra = []
        finally:
            crop_path.unlink(missing_ok=True)
        kept: list[dict] = []
        for item in extra:
            text = _keep_ocr_text(str(item.get("text") or ""), float(item.get("conf") or 0))
            if not text:
                continue
            kept.append(
                {
                    **item,
                    "text": text,
                    "x0": float(item["x0"]),
                    "y0": float(item["y0"]) + y0,
                    "x1": float(item["x1"]),
                    "y1": float(item["y1"]) + y0,
                }
            )
        col_x0, col_x1 = (
            min(float(item["x0"]) for item in previous["items"]),
            max(float(item["x1"]) for item in previous["items"]),
        )
        col_x0 = min(col_x0, min(float(item["x0"]) for item in nxt["items"]))
        col_x1 = max(col_x1, max(float(item["x1"]) for item in nxt["items"]))
        for item in _merge_row_items(kept):
            hangul = sum(1 for char in item["text"] if "\uac00" <= char <= "\ud7a3")
            hanja = sum(1 for char in item["text"] if "\u4e00" <= char <= "\u9fff")
            latin = sum(1 for char in item["text"] if char.isascii() and char.isalpha())
            if hangul < 4 and hanja < 2 and latin < 6:
                continue
            item = {**item, "x0": col_x0, "x1": col_x1}
            if all(_iou(item, existing) < 0.35 for existing in filled):
                filled.append(item)
    return filled


def _rapid_engine_params(
    ocr_dir: Path,
    rec_lang: str,
    *,
    strip: bool = False,
) -> dict:
    from rapidocr import EngineType, LangRec, ModelType, OCRVersion

    lang_map = {
        "korean": LangRec.KOREAN,
        "en": LangRec.EN,
        "ch": LangRec.CH,
    }
    models = ocr_dir / "models"
    use_v5 = _first_file(
        models,
        ("korean_PP-OCRv5_rec_mobile.onnx", "ch_PP-OCRv5_det_mobile.onnx"),
    ) is not None
    version = OCRVersion.PPOCRV5 if use_v5 else OCRVersion.PPOCRV4
    params: dict = {
        "Global.log_level": "error",
        "Rec.lang_type": lang_map.get(rec_lang, LangRec.KOREAN),
        "Rec.ocr_version": version,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Det.ocr_version": version,
        "Det.model_type": ModelType.MOBILE,
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Cls.ocr_version": version,
        "Cls.model_type": ModelType.MOBILE,
        "Cls.engine_type": EngineType.ONNXRUNTIME,
        "Det.limit_side_len": 960 if strip else 1920,
        "Global.max_side_len": 4096,
    }
    if strip:
        params["Det.limit_type"] = "max"
        params["Det.box_thresh"] = 0.3
        params["Det.unclip_ratio"] = 1.2
    det = _first_file(
        models,
        (
            "ch_PP-OCRv5_det_mobile.onnx",
            "ch_PP-OCRv4_det_mobile.onnx",
            "det.onnx",
        ),
    )
    rec = _first_file(models, _rec_model_names(rec_lang))
    cls = _first_file(
        models,
        (
            "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "cls.onnx",
        ),
    )
    rec_keys = {
        "korean": ("ppocrv5_korean_dict.txt", "korean_dict.txt"),
        "en": ("en_dict.txt",),
        "ch": ("ppocrv5_dict.txt", "ppocr_keys_v1.txt"),
    }
    keys = _first_file(models, rec_keys.get(rec_lang, ()))
    if det is not None:
        params["Det.model_path"] = str(det)
    if rec is not None:
        params["Rec.model_path"] = str(rec)
    if cls is not None:
        params["Cls.model_path"] = str(cls)
    if keys is not None:
        params["Rec.rec_keys_path"] = str(keys)
    return params


def _run_rapid_one(
    image: Path,
    ocr_dir: Path,
    rec_lang: str,
    *,
    strip: bool = False,
) -> list[dict]:
    from rapidocr import RapidOCR

    engine = RapidOCR(params=_rapid_engine_params(ocr_dir, rec_lang, strip=strip))
    if strip:
        items = _items_from_rapid(
            engine(str(image), box_thresh=0.3, unclip_ratio=1.2)
        )
    else:
        work_image, scale, cleanup = _prepare_image(image)
        try:
            items = _scale_items(_items_from_rapid(engine(str(work_image))), scale)
            items = _refill_missed_lines(image, items, ocr_dir, rec_lang)
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)
    if rec_lang == "korean":
        return _filter_kept_items(items)
    if rec_lang == "en":
        return [
            item
            for item in items
            if _plausible_english(str(item.get("text") or ""))
            and float(item.get("conf") or 0) >= 0.80
        ]
    if rec_lang == "ch":
        return [
            item
            for item in items
            if _plausible_hanja(str(item.get("text") or ""))
            and float(item.get("conf") or 0) >= 0.80
        ]
    return items


def _rec_model_names(rec_lang: str) -> tuple[str, ...]:
    return {
        "korean": (
            "korean_PP-OCRv5_rec_mobile.onnx",
            "korean_PP-OCRv4_rec_mobile.onnx",
            "korean_rec.onnx",
        ),
        "en": (
            "en_PP-OCRv5_rec_mobile.onnx",
            "en_PP-OCRv4_rec_mobile.onnx",
            "en_rec.onnx",
        ),
        "ch": (
            "ch_PP-OCRv5_rec_mobile.onnx",
            "ch_PP-OCRv4_rec_mobile.onnx",
            "ch_rec.onnx",
        ),
    }.get(rec_lang, ())


def _can_run_rec(ocr_dir: Path, rec_lang: str) -> bool:
    if rec_lang == "korean":
        return True
    return _first_file(ocr_dir / "models", _rec_model_names(rec_lang)) is not None


def _run_rapid(
    image: Path,
    ocr_dir: Path,
    lang: str,
    *,
    strip: bool = False,
) -> list[dict]:
    langs = [name for name in _rec_langs(lang) if _can_run_rec(ocr_dir, name)]
    if not langs:
        langs = ["korean"]
    if "korean" in langs and not strip and ("en" in langs or "ch" in langs):
        items = _run_rapid_one(image, ocr_dir, "korean")
        if "en" in langs:
            items = _merge_extra_script(
                items, _run_rapid_one(image, ocr_dir, "en"), _plausible_english
            )
        if "ch" in langs:
            items = _merge_extra_script(
                items, _run_rapid_one(image, ocr_dir, "ch"), _plausible_hanja
            )
        return items
    groups = [
        _run_rapid_one(image, ocr_dir, rec_lang, strip=strip) for rec_lang in langs
    ]
    return _merge_items(groups)


def _run_paddle(image: Path, ocr_dir: Path, lang: str) -> list[dict]:
    from paddleocr import PaddleOCR

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "1")
    paddle_lang = (
        "korean"
        if lang in {"ko+en", "ko+en+ch", "auto", "default"}
        else "ch" if lang in {"ch", "chinese", "hanja"} else lang
    )
    kwargs = {
        "lang": paddle_lang,
        "show_log": False,
        **_model_kwargs(ocr_dir),
    }
    try:
        engine = PaddleOCR(**kwargs)
    except TypeError:
        kwargs.pop("show_log", None)
        engine = PaddleOCR(**{k: v for k, v in kwargs.items() if k != "use_angle_cls"})

    if hasattr(engine, "ocr"):
        try:
            result = engine.ocr(str(image), cls=True)
        except TypeError:
            result = engine.ocr(str(image))
        items = _items_from_legacy_ocr(result)
        if items:
            return items
    if hasattr(engine, "predict"):
        result = engine.predict(str(image))
        items = _items_from_predict(result)
        if items:
            return items
    return []


def _run_ocr(
    image: Path,
    ocr_dir: Path,
    lang: str,
    *,
    strip: bool = False,
) -> list[dict]:
    try:
        return _run_rapid(image, ocr_dir, lang, strip=strip)
    except ImportError:
        pass
    except Exception as exc:
        raise SystemExit(f"OCR 실패: {exc}") from exc
    try:
        return _run_paddle(image, ocr_dir, lang)
    except ImportError as exc:
        raise SystemExit(
            "OCR 엔진이 없습니다. OCR 팩(ocr_helper와 models)을 다시 넣어 주세요."
        ) from exc


def main() -> int:
    args = _parse_args()
    image = Path(args.image)
    output = Path(args.output)
    ocr_dir = Path(args.ocr_dir) if args.ocr_dir else image.parent
    if not image.is_file():
        print(f"이미지 파일이 없습니다: {image}", file=sys.stderr)
        return 3
    try:
        items = _run_ocr(image, ocr_dir, args.lang, strip=args.strip)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"OCR 실패: {exc}", file=sys.stderr)
        return 3
    items.sort(key=lambda item: (float(item.get("y0") or 0), float(item.get("x0") or 0)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"items": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
